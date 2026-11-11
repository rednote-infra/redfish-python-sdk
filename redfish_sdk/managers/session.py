"""
Session service manager — manages active BMC sessions.

Provides:
- List sessions
- Get session
- Create session (login)
- Delete session (logout)

Session creation returns an X-Auth-Token in the response header.
The SDK can optionally switch to token-based auth after login.

"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List
from urllib.parse import urlsplit

from ..exceptions import RedfishAuthError
from ..models.session import Session
from .system_resources import select_member

if TYPE_CHECKING:
    from ..client import RedfishClient

logger = logging.getLogger(__name__)


class SessionServiceManager:
    """
    Manages Redfish Session resources.


    """

    def __init__(self, client: RedfishClient):
        self._client = client
        self._http = client._http_client

    def sessions(self) -> List[Session]:
        """
        Get the list of active sessions.


        """
        session_service = self._client._get_session_service()
        return self._client._get_collection(session_service.sessions.odata_id, Session)

    def get(self, session_id: str) -> Session:
        """
        Get a specific session by ID.


        """
        return select_member(self.sessions(), session_id)

    def create(
        self,
        username: str,
        password: str,
        switch_to_token_auth: bool = False,
    ) -> Session:
        """
        Create a new session (login to the BMC).

        The Redfish spec requires posting to the Sessions collection directly
        (not via SessionService), which may be at /redfish/v1/SessionService/Sessions
        or /redfish/v1/Sessions.

        After creation, the X-Auth-Token is returned in the response header.
        If switch_to_token_auth=True, the SDK client will use this token
        for subsequent requests instead of Basic Auth.

        A successful login reporting PasswordChangeRequired installs the
        restricted token even if switch_to_token_auth is False, then raises
        RedfishPasswordChangeRequiredError. Use its account_uri for recovery
        and close/logout afterward. A surrounding client context cleans up
        the restricted session if the exception escapes its body.



        Args:
            username: BMC username
            password: BMC password
            switch_to_token_auth: If True, switch client to token-based auth

        Returns:
            Session resource with x_auth_token populated
        """
        # Use the Sessions link from the root service links (direct sessions endpoint)
        root = self._client._get_root()
        sessions_url = None

        if root.links and root.links.sessions:
            sessions_url = root.links.sessions.odata_id
        else:
            # Fallback to session service
            session_service = self._client._get_session_service()
            sessions_url = session_service.sessions.odata_id

        body = {"UserName": username, "Password": password}

        response = self._http.post_raw(sessions_url, body=body)

        restriction = self._http._response_error(response, sessions_url)
        if restriction:
            token = response.headers.get("X-Auth-Token")
            if token:
                self._http.set_auth_token(
                    token, session_location=response.headers.get("Location"),
                    session_collection_uri=sessions_url, username=username, password=password,
                )
            raise restriction

        # Some conforming BMCs return only token and Location headers.
        session_data = response.json() if response.text.strip() else {}
        location = response.headers.get("Location")
        if location:
            session_data.setdefault("@odata.id", location)
            path = urlsplit(location).path.rstrip("/")
            session_data.setdefault("Id", path.rsplit("/", 1)[-1])
        session = Session.model_validate(session_data)

        # Extract X-Auth-Token from response headers
        token = response.headers.get("X-Auth-Token")
        if token:
            session.x_auth_token = token
            logger.info("Session created successfully, token acquired")

            if switch_to_token_auth:
                self._http.set_auth_token(
                    token,
                    session_location=location,
                    session_collection_uri=sessions_url,
                    username=username,
                    password=password,
                )
        elif switch_to_token_auth:
            raise RedfishAuthError(401)

        return session

    def delete(self, session_id: str) -> str:
        """
        Delete a session (logout).



        Args:
            session_id: Session ID to delete

        Returns:
            Response body (usually empty)
        """
        session = select_member(self.sessions(), session_id)
        result = self._http.delete(session.odata_id)
        self._http.clear_active_session(session.odata_id)
        logger.info("Session %s deleted", session_id)
        return result
