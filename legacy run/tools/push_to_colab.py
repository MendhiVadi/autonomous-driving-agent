"""Upload the validated CARLA notebook/data through gcloud's user login."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import subprocess
import sys
import uuid

import requests

ROOT = Path(__file__).resolve().parents[1]
GCLOUD = Path(os.environ["LOCALAPPDATA"]) / "Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd"
API = "https://www.googleapis.com/drive/v3/files"
FIELDS = "id,name,mimeType,parents,webViewLink,md5Checksum,size"


class DriveAccessRequired(RuntimeError):
    pass


def checked(response):
    if response.status_code == 403 and "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in response.text:
        raise DriveAccessRequired("Google login needs Drive access. Run gcloud auth login --enable-gdrive-access.")
    if not response.ok:
        message = response.json().get("error", {}).get("message", response.reason)
        raise RuntimeError(f"Drive returned {response.status_code}: {message}")
    return response.json()


def escaped(value):
    return value.replace("\\", "\\\\").replace("'", "\\'")


def matching(session, parent, name):
    query = f"trashed = false and '{escaped(parent)}' in parents and name = '{escaped(name)}'"
    result = checked(session.get(API, params={"q": query, "fields": f"files({FIELDS}),nextPageToken",
                                              "pageSize": 100}, timeout=30))
    if result.get("nextPageToken"):
        raise RuntimeError(f"Too many files with the same name: {name}")
    return result.get("files", [])


def folder(session, parent, name):
    items = matching(session, parent, name)
    if len(items) > 1 or (items and items[0]["mimeType"] != "application/vnd.google-apps.folder"):
        raise RuntimeError(f"The destination '{name}' is ambiguous or isn't a folder.")
    if items:
        return items[0]
    return checked(session.post(API, params={"fields": FIELDS}, json={"name": name,
        "mimeType": "application/vnd.google-apps.folder", "parents": [parent]}, timeout=30))


def upload(session, parent, path, mime=None):
    path = Path(path)
    data = path.read_bytes()
    digest = hashlib.md5(data).hexdigest()
    name = path.name
    items = matching(session, parent, name)
    for item in items:
        if item.get("md5Checksum") == digest:
            print(f"Already uploaded: {name}", flush=True)
            return item
    if items:
        # Preserve any existing different notebook/file as a separate version.
        name = f"{path.stem}-{digest[:8]}{path.suffix}"
        versions = matching(session, parent, name)
        for item in versions:
            if item.get("md5Checksum") == digest:
                return item
        if versions:
            raise RuntimeError(f"Conflicting upload version: {name}")
    mime = mime or mimetypes.guess_type(name)[0] or "application/octet-stream"
    metadata = json.dumps({"name": name, "parents": [parent], "mimeType": mime}).encode()
    boundary = "carla_" + uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()
            + metadata + f"\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n".encode()
            + data + f"\r\n--{boundary}--\r\n".encode())
    item = checked(session.post("https://www.googleapis.com/upload/drive/v3/files",
        params={"uploadType": "multipart", "fields": FIELDS}, data=body,
        headers={"Content-Type": f"multipart/related; boundary={boundary}"}, timeout=90))
    verified = checked(session.get(f"{API}/{item['id']}", params={"fields": FIELDS}, timeout=30))
    if verified.get("md5Checksum") != digest:
        response = session.get(f"{API}/{item['id']}", params={"alt": "media"}, timeout=60)
        response.raise_for_status()
        if hashlib.md5(response.content).hexdigest() != digest:
            raise RuntimeError(f"Upload checksum verification failed: {name}")
    print(f"Uploaded and verified: {name}", flush=True)
    return verified


def main():
    os.chdir(ROOT)
    manifest = json.loads((ROOT / "episodes/expert/collection-1789030643366201300.json").read_text(encoding="utf-8"))
    from prepare_colab_bundle import prepare
    prepare(ROOT / "episodes/expert/collection-1789030643366201300.json", ROOT / "exports/CARLA_colab_training.zip")
    login = subprocess.run([str(GCLOUD), "auth", "print-access-token"], capture_output=True, text=True)
    if login.returncode:
        raise DriveAccessRequired("Google command-line login could not refresh. Sign in again.")
    session = requests.Session()
    session.headers["Authorization"] = "Bearer " + login.stdout.strip()
    carla_folder = folder(session, "root", "CARLA")
    episodes_folder = folder(session, carla_folder["id"], "episodes")
    uploaded = [upload(session, episodes_folder["id"], ROOT / item["path"], "application/jsonl")
                for item in manifest["episodes"]]
    notebook = upload(session, carla_folder["id"], ROOT / "colab_train_policy.ipynb",
                      "application/vnd.google.colaboratory")
    bundle = upload(session, carla_folder["id"], ROOT / "exports/CARLA_colab_training.zip")
    report = upload(session, carla_folder["id"], ROOT / "exports/CARLA_colab_training.validation.json")
    receipt = {"verified": True, "folder": carla_folder, "episodes_folder": episodes_folder,
               "episode_count": len(uploaded), "episodes": uploaded, "notebook": notebook,
               "bundle": bundle, "validation": report}
    (ROOT / "exports/colab_upload_receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps({"uploaded": True, "episodes": len(uploaded),
                      "notebook": notebook.get("webViewLink"), "folder": carla_folder.get("webViewLink")}))


if __name__ == "__main__":
    try:
        main()
    except DriveAccessRequired as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    except (RuntimeError, requests.RequestException) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
