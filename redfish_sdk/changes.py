"""Optional client-side mutation plans; no atomicity or rollback is promised."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from enum import Enum
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Callable, Optional, Union
from urllib.parse import urlsplit

from pydantic import BaseModel

from ._errors import error_from_response
from ._redaction import redact_diagnostic, redact_for_log
from .exceptions import RedfishException, RedfishPreconditionFailedError, RedfishValidationError
from .request import _UNSET_BODY, HttpMethod
from .response import GenericResponse

if TYPE_CHECKING:
    from .client import RedfishClient

_MUTATIONS = frozenset({HttpMethod.POST, HttpMethod.PUT, HttpMethod.PATCH, HttpMethod.DELETE})
_CAPTURABLE = frozenset({HttpMethod.PUT, HttpMethod.PATCH, HttpMethod.DELETE})
_IF_MATCH = "If-Match"
_IF_NONE_MATCH = "If-None-Match"
_ETAG = "ETag"
_WEAK_ETAG_PREFIX = "W/"
_ENTITY_TAG = re.compile(r"(?:" + re.escape(_WEAK_ETAG_PREFIX) + r')?"[\x21\x23-\x7e\x80-\xff]*"\Z')
_WILDCARD = "*"


def _json_default(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True, exclude_unset=True)
    if isinstance(value, Enum):
        return value.value
    raise TypeError("Change payloads must contain JSON values or Pydantic models")


def _freeze(value):
    if value is _UNSET_BODY:
        return None
    try:
        return json.dumps(value, default=_json_default, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise RedfishValidationError("Change payloads must be serializable finite JSON values") from exc


class ChangeStatus(str, Enum):
    """Per-operation outcomes; accepted operations have not finished applying."""

    SUCCESS = "success"
    ACCEPTED = "accepted"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class ChangeOperation:
    """Immutable wire intent. Body/baseline properties return detached copies."""

    method: str
    uri: str = field(repr=False)
    body_json: Optional[str] = field(default=None, repr=False)
    before_json: Optional[str] = field(default=None, repr=False)
    expected_etag: Optional[str] = field(default=None, repr=False)
    if_none_match: Optional[str] = field(default=None, repr=False)

    @property
    def has_body(self) -> bool:
        return self.body_json is not None

    @property
    def body(self) -> Any:
        return json.loads(self.body_json) if self.has_body else None

    @property
    def before(self) -> Any:
        return json.loads(self.before_json) if self.before_json is not None else None


@dataclass(frozen=True)
class ChangeValidationIssue:
    """A local validation failure, indexed in staging order."""

    operation_index: int
    error: RedfishException


@dataclass(frozen=True)
class ChangeOperationResult:
    """Outcome of one intent; attempted writes can have an uncertain outcome."""

    operation_index: int
    operation: ChangeOperation
    status: ChangeStatus
    attempted: bool = False
    response: Optional[GenericResponse] = field(default=None, repr=False)
    error: Optional[RedfishException] = None
    reason: str = ""
    outcome_unknown: bool = False


@dataclass(frozen=True)
class ChangeSetResult:
    """Ordered outcomes, including skips; no rollback is attempted.

    SUCCESS means HTTP completion, not proof of a desired hardware state.
    ACCEPTED retains task metadata and must be monitored separately. Transport
    failures and server errors can leave a write's application uncertain.
    """

    results: tuple[ChangeOperationResult, ...]
    dry_run: bool = False

    @property
    def successful(self) -> bool:
        return not self.dry_run and all(item.status is ChangeStatus.SUCCESS for item in self.results)

    @property
    def pending(self) -> bool:
        return any(item.status is ChangeStatus.ACCEPTED for item in self.results)

    @property
    def has_uncertain_outcomes(self) -> bool:
        return any(item.outcome_unknown for item in self.results)

    @property
    def is_partial(self) -> bool:
        """Report known partial application or an uncertain attempted write."""
        applied = any(item.status in (ChangeStatus.SUCCESS, ChangeStatus.ACCEPTED) for item in self.results)
        incomplete = any(item.status in (ChangeStatus.FAILED, ChangeStatus.SKIPPED) for item in self.results)
        return self.has_uncertain_outcomes or applied and incomplete


ChangeValidator = Callable[[ChangeOperation], None]


def _diff(before, after, before_present, after_present, *, merge, path=(), output=None):
    """Compare intent with a supplied snapshot; explicit null remains a value."""
    if output is None:
        output = []
    if not before_present and not after_present:
        return output
    if after_present and isinstance(after, dict) and (
        after or before_present and isinstance(before, dict) or merge and not path
    ):
        keys = set(after)
        if not merge and before_present and isinstance(before, dict):
            keys.update(before)
        for key in sorted(keys):
            known = before_present and isinstance(before, dict) and key in before
            _diff(before.get(key) if known else None, after.get(key), known, key in after,
                  merge=merge, path=(*path, key), output=output)
    elif not before_present or not after_present or _freeze(before) != _freeze(after):
        pointer = "".join("/" + token.replace("~", "~0").replace("/", "~1") for token in path)
        row = {"path": pointer, "before_present": before_present, "after_present": after_present}
        if before_present:
            row["before"] = before
        if after_present:
            row["after"] = after
        output.append(row)
    return output


def _display_at(value, pointer):
    for token in pointer.split("/")[1:]:
        if not isinstance(value, dict):
            break  # A sensitive ancestor was replaced with a redacted scalar.
        value = value[token.replace("~1", "/").replace("~0", "~")]
    return value


def _check_tag(value):
    if value is not None and (not isinstance(value, str) or not (value == _WILDCARD or _ENTITY_TAG.fullmatch(value))):
        raise RedfishValidationError("Preconditions require a single quoted ETag or wildcard")


class ChangeSet:
    """Stage, inspect, validate and execute an ordered set of explicit requests.

    Staging, plan(), to_json(), validate() and dry-run commit never use the
    network. capture_etags() explicitly reads target resources. commit() checks
    supplied ETags before the first write by default and also sends conditional
    headers to close the preflight/write race. No schema validation is inferred;
    supply a validator for service-specific constraints. Server-side Settings and
    ApplyTime annotations belong in the explicit body and target Settings URI.

    Operations execute once in staging order, stopping at the first failure by
    default. Order is request submission order; 202 tasks are not polled and
    can still be running when later requests start. Multiple writes to one URI
    are not merged or assigned refreshed
    ETags automatically. A later operation can therefore fail its original ETag
    after an earlier write. Once a write is attempted the plan is consumed,
    including on failure: create and inspect a new plan for any retry. Do not
    share a change set between concurrent tasks/threads.
    """

    def __init__(self, client: RedfishClient):
        self._client = client
        self._operations: list[ChangeOperation] = []
        self._executed = False
        self._validating = False

    @property
    def operations(self) -> tuple[ChangeOperation, ...]:
        return tuple(self._operations)

    def _ensure_pending(self):
        if self._validating:
            raise RedfishValidationError("Change set cannot be modified during validation")
        if self._executed:
            raise RedfishValidationError("Change set has already been executed; create a new plan to retry")

    def stage(self, method: Union[HttpMethod, str], uri: str, *, body: Any = _UNSET_BODY,
              before: Any = _UNSET_BODY, expected_etag: Optional[str] = None,
              if_none_match: Optional[str] = None) -> ChangeSet:
        """Snapshot an intent; no GET, mutation or implicit baseline capture.

        before is caller-supplied diff context, not an enforced precondition.
        expected_etag/if_none_match are explicit conditional request validators.
        Models preserve aliases, supplied nulls and Settings/ApplyTime metadata.
        """
        self._ensure_pending()
        if not isinstance(method, str):
            raise RedfishValidationError("Change method must be an HttpMethod or string")
        if any(value is not None and not isinstance(value, str) for value in (expected_etag, if_none_match)):
            raise RedfishValidationError("Preconditions must be immutable ETag strings")
        target = self._client._http_client._resolve_url(uri)
        if urlsplit(target).fragment:
            raise RedfishValidationError("Change targets must not contain fragments")
        self._operations.append(ChangeOperation(method.upper(), target, _freeze(body), _freeze(before),
                                                expected_etag, if_none_match))
        return self

    def validate(self, validator: Optional[ChangeValidator] = None) -> tuple[ChangeValidationIssue, ...]:
        """Validate every operation locally, retaining each failure unchanged.

        Custom validators must raise RedfishValidationError (or another
        RedfishException) for an invalid intent. They cannot change the plan.
        Unexpected programming errors propagate before any write.
        """
        if validator is not None and not callable(validator):
            raise RedfishValidationError("validator must be callable")
        if self._validating:
            raise RedfishValidationError("Change set is already being validated")
        self._validating = True
        issues = []
        try:
            for index, operation in enumerate(self.operations):
                try:
                    if operation.method not in _MUTATIONS:
                        raise RedfishValidationError("Change sets support only POST, PUT, PATCH and DELETE")
                    self._client._http_client._resolve_url(operation.uri)
                    if operation.method in (HttpMethod.PATCH, HttpMethod.PUT) and not operation.has_body:
                        raise RedfishValidationError("PATCH and PUT changes require an explicit body")
                    _check_tag(operation.expected_etag)
                    _check_tag(operation.if_none_match)
                    if operation.expected_etag is not None and operation.if_none_match is not None:
                        raise RedfishValidationError("Use either expected_etag or if_none_match, not both")
                    if validator:
                        validator(operation)
                except RedfishException as exc:
                    issues.append(ChangeValidationIssue(index, exc))
        finally:
            self._validating = False
        return tuple(issues)

    def plan(self, *, include_sensitive: bool = False) -> list[dict[str, Any]]:
        """Return a detached deterministic intent/diff; redact display by default.

        Missing baseline values are marked unknown, not guessed from the BMC.
        PATCH diffs inspect supplied fields; PUT includes removed baseline keys.
        POST describes the submitted body, not an action's predicted effects.
        Diff rows are computed before redaction so secret changes stay visible.
        """
        if not isinstance(include_sensitive, bool):
            raise RedfishValidationError("include_sensitive must be a boolean")
        output = []
        for index, operation in enumerate(self.operations):
            before, after = operation.before, operation.body
            rows = _diff(before, after, operation.before_json is not None,
                         operation.has_body and operation.method != HttpMethod.DELETE,
                         merge=operation.method == HttpMethod.PATCH)
            if not include_sensitive:
                before, after = redact_for_log(before), redact_for_log(after)
                for row in rows:
                    if row["before_present"]:
                        row["before"] = _display_at(before, row["path"])
                    if row["after_present"]:
                        row["after"] = _display_at(after, row["path"])
            output.append({"operation_index": index, "method": operation.method,
                           "uri": operation.uri if include_sensitive else redact_diagnostic(operation.uri),
                           "baseline_available": operation.before_json is not None,
                           "body_present": operation.has_body, "body": after,
                           "expected_etag": operation.expected_etag, "if_none_match": operation.if_none_match,
                           "diff": rows})
        return output

    def to_json(self, *, include_sensitive: bool = False) -> str:
        """Serialize an inspectable plan; sensitive export requires explicit opt-in."""
        return json.dumps(self.plan(include_sensitive=include_sensitive), sort_keys=True, indent=2, allow_nan=False)

    def _response_failure(self, operation, response, method):
        return error_from_response(
            response.status_code, response.text, response.headers,
            method=method, path=operation.uri,
            secrets=self._client._http_client._diagnostic_secrets(),
            allow_redirect_success=False,
        )

    def _read(self, operation):
        response = self._client.request(HttpMethod.GET, operation.uri)
        if not HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES:
            raise self._response_failure(operation, response, HttpMethod.GET.value)
        return response

    @staticmethod
    def _precondition(operation, response):
        actual = response.headers.get(_ETAG)
        if operation.expected_etag not in (None, _WILDCARD) and actual != operation.expected_etag:
            raise RedfishPreconditionFailedError(HTTPStatus.PRECONDITION_FAILED, "Resource ETag changed or is unavailable")
        if operation.if_none_match is not None:
            excluded_match = operation.if_none_match == _WILDCARD or (
                actual is not None and actual.removeprefix(_WEAK_ETAG_PREFIX)
                == operation.if_none_match.removeprefix(_WEAK_ETAG_PREFIX)
            )
            if excluded_match:
                raise RedfishPreconditionFailedError(HTTPStatus.PRECONDITION_FAILED, "Resource matches the excluded precondition")
            if actual is None:
                raise RedfishPreconditionFailedError(HTTPStatus.PRECONDITION_FAILED, "Resource ETag is unavailable")

    def capture_etags(self, *, include_before: bool = True) -> ChangeSet:
        """GET existing PATCH/PUT/DELETE targets; snapshot ETags and optional JSON.

        All reads must succeed before snapshots are installed. Existing explicit
        conditions are checked and never overwritten. Creation preconditions are
        left intact. Only HTTP ETag is used, never @Redfish.Settings.ETag from an
        active resource. Stage the actual Settings URI to capture its validator.
        """
        self._ensure_pending()
        if not isinstance(include_before, bool):
            raise RedfishValidationError("include_before must be a boolean")
        issues = self.validate()
        if issues:
            raise issues[0].error
        updated, reads = [], {}
        for operation in self.operations:
            if operation.method not in _CAPTURABLE or operation.if_none_match is not None:
                updated.append(operation)
                continue
            if operation.uri not in reads:
                reads[operation.uri] = self._read(operation)
            response = reads[operation.uri]
            self._precondition(operation, response)
            tag = response.headers.get(_ETAG)
            if tag is None or tag == _WILDCARD:
                raise RedfishValidationError("Resource did not provide a capturable HTTP ETag")
            _check_tag(tag)
            if include_before and not isinstance(response.json_data, dict):
                raise RedfishValidationError("Baseline capture requires a JSON resource object")
            updated.append(replace(operation, expected_etag=operation.expected_etag or tag,
                                   before_json=_freeze(response.json_data) if include_before else operation.before_json))
        self._operations = updated
        return self

    def _blocked(self, errors, reason, *, dry_run=False):
        return ChangeSetResult(tuple(ChangeOperationResult(
            index, operation, ChangeStatus.FAILED if index in errors else ChangeStatus.SKIPPED,
            error=errors.get(index), reason=reason,
        ) for index, operation in enumerate(self.operations)), dry_run=dry_run)

    def commit(self, *, dry_run: bool = False, check_etags: bool = True,
               continue_on_error: bool = False, validator: Optional[ChangeValidator] = None) -> ChangeSetResult:
        """Validate/preflight the whole plan, then execute in staging order.

        dry_run performs no network requests. check_etags=False skips read-side
        comparisons but still sends the staged conditional headers. Preconditions
        are always enforced by the server. Default transport policy never replays
        writes; caller-installed adapters must also disable write retries.
        """
        self._ensure_pending()
        if any(not isinstance(value, bool) for value in (dry_run, check_etags, continue_on_error)):
            raise RedfishValidationError("Commit options must be booleans")
        issues = self.validate(validator)
        if issues:
            return self._blocked({issue.operation_index: issue.error for issue in issues},
                                 "Plan validation failed; no mutations were sent", dry_run=dry_run)
        if dry_run:
            return self._blocked({}, "Dry run; no network requests performed", dry_run=True)
        if check_etags:
            errors, reads = {}, {}
            for index, operation in enumerate(self.operations):
                if operation.expected_etag is None and operation.if_none_match is None:
                    continue
                try:
                    if operation.uri not in reads:
                        reads[operation.uri] = self._read(operation)
                    self._precondition(operation, reads[operation.uri])
                except RedfishException as exc:
                    if exc.status_code == HTTPStatus.NOT_FOUND and operation.if_none_match is not None:
                        continue
                    errors[index] = exc
            if errors:
                return self._blocked(errors, "Plan preconditions failed; no mutations were sent")
        results = []
        stopped = False
        for index, operation in enumerate(self.operations):
            if stopped:
                results.append(ChangeOperationResult(index, operation, ChangeStatus.SKIPPED,
                                                     reason="A preceding operation failed"))
                continue
            self._executed = True
            headers = {}
            if operation.expected_etag is not None:
                headers[_IF_MATCH] = operation.expected_etag
            if operation.if_none_match is not None:
                headers[_IF_NONE_MATCH] = operation.if_none_match
            response = None
            try:
                response = self._client.request(operation.method, operation.uri, headers=headers,
                                                body=operation.body if operation.has_body else _UNSET_BODY)
                if not HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES:
                    raise self._response_failure(operation, response, operation.method)
                status = ChangeStatus.ACCEPTED if response.status_code == HTTPStatus.ACCEPTED else ChangeStatus.SUCCESS
                results.append(ChangeOperationResult(index, operation, status, attempted=True, response=response))
            except RedfishException as exc:
                unknown = (exc.status_code == 0 or exc.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR
                           or HTTPStatus.MULTIPLE_CHOICES <= exc.status_code < HTTPStatus.BAD_REQUEST)
                results.append(ChangeOperationResult(
                    index, operation, ChangeStatus.FAILED, attempted=True,
                    response=response, error=exc, outcome_unknown=unknown,
                ))
                stopped = not continue_on_error
        return ChangeSetResult(tuple(results))
