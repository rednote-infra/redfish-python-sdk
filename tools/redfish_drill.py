import base64
import json
import os

import urllib3

### How to use this script ###
# 1. change the ODATA_JSON_DIR to the directory you want to save json files
# 2. set environment variables: BMC_IP, BMC_USER, BMC_PASSWORD
# 3. run the script, it will recursively get all json files for odata.id and save them to ODATA_JSON_DIR

redfish_root_odata_id = "/redfish/v1/"
redfish_system_odata_id = "/redfish/v1/Systems/1"
redfish_chassis_odata_id = "/redfish/v1/Chassis/1"

rc = None
ODATA_JSON_DIR = ""

# ignore odata.id list
ignore_odata_id = [
    "/redfish/v1/Managers/1/LogServices",  # log
    "/redfish/v1/Chassis/1/Sensors",  # sensors
    "/redfish/v1/Chassis/1/Thermal",  # temperature
    "/redfish/v1/Chassis/Self",  # self
    "/redfish/v1/Systems/Self",  # self
    "/redfish/v1/Managers/Self",  # self
    "/redfish/v1/EventService",  # event
    "/redfish/v1/Systems/system/LogServices",  # log
]
# key for odata.id
odataid_key = "@odata.id"

# onley drill these resources
# if it is empty, will drill all resources
resource_items = []

# odata.id cache
all_odata_id = {}


# get odata.id file path
def get_odata_id_file(odata_id, dir):
    odata_id = str.replace(odata_id, "/", "_")
    if odata_id.startswith("_"):
        odata_id = odata_id[1:]
    return f"{dir}/{odata_id}.json"


# loop to retrieve all data
def drill_data(k, v):
    if v is None:
        return
    # may be value is str
    if k == odataid_key and v not in ignore_odata_id and v not in all_odata_id:
        is_resource = False
        for item in resource_items:
            if item in v:
                is_resource = True
                break
        if len(resource_items) > 0 and not is_resource:
            return

        all_odata_id[v] = None
        odata_path = get_odata_id_file(v, ODATA_JSON_DIR)
        if os.path.exists(odata_path):
            print(f"odata.id already exists: {v}")
            return

        print(f"save odata.id: {v} to {odata_path}")
        try:
            content = rc.get(v)
        except Exception as e:
            print(f"[ERROR] 请求 {v} 失败: {type(e).__name__}: {e}")
            return
        if content is None:
            return

        with open(odata_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(content, indent=4))

        # may be content has odata.id
        for kk, vv in content.items():
            drill_data(kk, vv)

        return
    # may be value is list
    if type(v) is list:
        for item in v:
            if type(item) is not dict:
                continue
            for kk, vv in item.items():
                drill_data(kk, vv)

    # may be value is dict
    if type(v) is not dict:
        return

    for kk, vv in v.items():
        drill_data(kk, vv)


def drill_odataid(odata_id):
    """drill odata.id recursively."""
    content = rc.get(odata_id)
    if content is None:
        print(f"[WARN] 无法获取入口资源 {odata_id}，跳过")
        return
    for k, v in content.items():
        drill_data(k, v)


def save_all_odata_id():
    """save all odata.id to file."""
    with open(f"{ODATA_JSON_DIR}/all_odata_id.json", "w", encoding="utf-8") as f:
        f.writelines("\n".join(all_odata_id.keys()))


class Redfish:
    """Redfish client."""

    def __init__(self, base_url, username, password):
        self.host = "https://" + base_url
        self.user = username
        self.password = password
        auth_str = f"{username}:{password}"
        encoded = base64.b64encode(auth_str.encode()).decode("utf-8")
        self.header = {
            "Content-type": "application/json",
            "Authorization": f"Basic {encoded}",
            "IF-Match": "*",
        }

    def get(self, url, **kwargs):
        full_url = self.host + url
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        http = urllib3.PoolManager(cert_reqs="CERT_NONE")
        try:
            rsp = http.request(
                "GET",
                full_url,
                headers=self.header,
                timeout=urllib3.Timeout(30.0),
                **kwargs,
            )
        except Exception as e:
            print(f"[ERROR] HTTP 请求失败: GET {full_url}")
            print(f"        原因: {type(e).__name__}: {e}")
            return None
        if 200 <= rsp.status < 300:
            etag = rsp.headers.get("ETag")
            if etag is not None:
                self.header["IF-Match"] = etag
            return json.loads(rsp.data.decode("utf-8"))
        print(f"[ERROR] HTTP {rsp.status} {rsp.reason}: GET {full_url}")
        return None


if __name__ == "__main__":
    ODATA_JSON_DIR = "./testdata"

    os.makedirs(ODATA_JSON_DIR, exist_ok=True)

    bmc_ip = os.environ.get("BMC_IP")
    bmc_username = os.environ.get("BMC_USER")
    bmc_password = os.environ.get("BMC_PASSWORD")

    if not bmc_ip or not bmc_username or not bmc_password:
        raise SystemExit(
            "Please set environment variables: BMC_IP, BMC_USER, BMC_PASSWORD"
        )

    rc = Redfish(bmc_ip, bmc_username, bmc_password)

    # resource_items = ["Drive", "Processor", "Memory", "Network", "Fan", "Power"]

    for odata_id in [redfish_system_odata_id, redfish_chassis_odata_id]:
        drill_odataid(odata_id)

    save_all_odata_id()
