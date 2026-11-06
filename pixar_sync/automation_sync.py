#!/usr/bin/env python3
"""Deploy exactly one allowlisted Lenovo charging automation through HA's editor API.

Does not edit automations.yaml or configuration.yaml. No HA device service calls.
It refuses to replace an automation modified outside this synchronizer.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

import yaml

AUTOMATION_ID = 'pixar_sync_lenovo_charge_40_80_v1'
ALIAS = 'Lenovo - Charge automatique Shelly 40-80 %'
SENSOR = 'sensor.lenovo_tb_x606f_battery_level'
SWITCH = 'switch.cuisine_prise_tablette_ha'
BASE = 'http://supervisor/core/api'
BACKUP_DIR = Path('/data/automation-backups')
STATE_FILE = Path('/data/automation-sync-state.json')


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode('utf-8')).hexdigest()


def validate(source):
    """Strict allowlist prevents arbitrary GitHub YAML from controlling other devices."""
    if len(source) > 20_000:
        raise ValueError('Automation too large')
    try:
        obj = yaml.safe_load(source)
    except yaml.YAMLError as exc:
        raise ValueError("Invalid automation YAML") from exc
    if not isinstance(obj, dict):
        raise ValueError('Automation must be a YAML mapping')
    expected_keys = {'id', 'alias', 'description', 'triggers', 'conditions', 'actions', 'mode'}
    if set(obj) != expected_keys or obj['id'] != AUTOMATION_ID or obj['alias'] != ALIAS:
        raise ValueError('Unexpected automation identity or fields')
    if not isinstance(obj['description'], str) or len(obj['description']) > 500:
        raise ValueError('Unexpected description')
    if obj['mode'] != 'single' or obj['conditions'] != []:
        raise ValueError('Unexpected mode or conditions')
    if obj['triggers'] != [
        {'trigger': 'state', 'entity_id': SENSOR},
        {'trigger': 'time_pattern', 'minutes': '/5'},
        {'trigger': 'homeassistant', 'event': 'start'},
    ]:
        raise ValueError('Unexpected triggers')
    if not isinstance(obj['actions'], list) or len(obj['actions']) != 1:
        raise ValueError('Unexpected action list')
    main = obj['actions'][0]
    if not isinstance(main, dict) or set(main) != {'choose'} or not isinstance(main['choose'], list):
        raise ValueError('Only choose actions are permitted')
    choices = main['choose']
    if len(choices) != 3:
        raise ValueError('Expected exactly three charging cases')
    for i, choice in enumerate(choices):
        if not isinstance(choice, dict) or set(choice) != {'alias', 'conditions', 'sequence'}:
            raise ValueError('Unexpected choice structure')
        if not isinstance(choice['alias'], str) or len(choice['alias']) > 150:
            raise ValueError('Unexpected branch alias')
        if not isinstance(choice['conditions'], list) or len(choice['conditions']) != 1:
            raise ValueError('Expected exactly one condition per choice')
        if choice['sequence'] != [{'action': 'switch.turn_off' if i == 2 else 'switch.turn_on',
                                   'target': {'entity_id': SWITCH}}]:
            raise ValueError('Non-Shelly or unapproved action detected')
    safety = choices[0]['conditions'][0]
    if not isinstance(safety, dict) or set(safety) != {'condition', 'value_template'}:
        raise ValueError('Unexpected safety condition')
    if safety['condition'] != 'template':
        raise ValueError('Safety must be a template condition')
    expected_safety = ("{% set b = states.sensor.lenovo_tb_x606f_battery_level %}\n"
                       "{{ b is none\n"
                       "   or not is_number(b.state)\n"
                       "   or (as_timestamp(now()) - as_timestamp(b.last_updated)) > 7200 }}")
    # Normalize leading indentation from YAML multiline scalar.
    if ' '.join(safety['value_template'].split()) != ' '.join(expected_safety.split()):
        raise ValueError('Unexpected safety formula')
    thresholds = []
    for i in (1, 2):
        condition = choices[i]['conditions'][0]
        if not isinstance(condition, dict) or set(condition) != {'condition', 'entity_id',
                                                                'below' if i == 1 else 'above'}:
            raise ValueError('Unexpected threshold condition')
        if condition['condition'] != 'numeric_state' or condition['entity_id'] != SENSOR:
            raise ValueError('Unexpected threshold sensor')
        value = condition['below' if i == 1 else 'above']
        if type(value) is not int:
            raise ValueError('Threshold must be an integer')
        thresholds.append(value)
    if not (21 <= thresholds[0] <= 61 and 69 <= thresholds[1] <= 91
            and thresholds[1] - thresholds[0] >= 15):
        raise ValueError('Unsafe charging thresholds')
    return obj


def request(token, method, endpoint, payload=None, missing_ok=False):
    if not token:
        raise ValueError('Supervisor token unavailable')
    body = None if payload is None else json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(BASE + endpoint, data=body, method=method, headers={
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'User-Agent': 'HomeAssistant-Pixar-Sync/0.3.1',
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status not in (200, 201, 204):
                raise ValueError('Home Assistant API returned an unexpected response')
            # /states can exceed 256 KB on a well-equipped Home Assistant.
            # Read up to 8 MB plus one byte, and reject an oversized reply
            # rather than attempting to parse truncated JSON.
            max_response_bytes = 8_000_000
            data = resp.read(max_response_bytes + 1)
            if len(data) > max_response_bytes:
                raise ValueError('Home Assistant API reply exceeds 8 MB; no changes made')
            try:
                return json.loads(data) if data else None
            except json.JSONDecodeError as exc:
                raise ValueError('Invalid JSON response from Home Assistant; no changes made') from exc
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and missing_ok:
            return None
        # Avoid printing response bodies, which may include confidential HA details.
        raise ValueError('Home Assistant refused '+method+' '+endpoint+
                         ' (HTTP '+str(exc.code)+')') from exc


def load_record():
    if not STATE_FILE.exists():
        return None
    obj = json.loads(STATE_FILE.read_text('utf-8'))
    if not isinstance(obj, dict) or obj.get('id') != AUTOMATION_ID:
        raise ValueError('Unexpected synchronizer state; no changes made')
    return obj


def save_record(source_sha, remote):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {'id': AUTOMATION_ID, 'source_sha256': source_sha,
            'remote_sha256': digest(remote),
            'synced_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    temp = STATE_FILE.with_suffix('.tmp')
    with open(temp, 'x', encoding='utf-8') as out:
        os.chmod(temp, 0o600)
        json.dump(data, out, indent=2, ensure_ascii=False)
    os.replace(temp, STATE_FILE)


def backup(remote):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    name = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json'
    path = BACKUP_DIR / name
    with open(path, 'x', encoding='utf-8') as out:
        os.chmod(path, 0o600)
        json.dump({'id': AUTOMATION_ID, 'previous': remote}, out, indent=2, ensure_ascii=False)
    return path


def run(source, source_sha):
    automation = validate(source)
    token = os.environ.get('SUPERVISOR_TOKEN', '')
    if not token:
        raise ValueError('Supervisor token unavailable; automation unchanged')
    old = load_record()
    path = '/config/automation/config/' + AUTOMATION_ID
    remote = request(token, 'GET', path, missing_ok=True)
    if remote is not None and (not isinstance(remote, dict) or remote.get('id') != AUTOMATION_ID):
        raise ValueError('Existing automation identity mismatch; refusing update')
    if old:
        if remote is None:
            raise ValueError('Previously deployed automation is missing; not recreating')
        if digest(remote) != old.get('remote_sha256'):
            raise ValueError('Automation changed manually; refusing to overwrite')
        if old.get('source_sha256') == source_sha:
            print('[pixar-automation] Lenovo charging automation already up to date', flush=True)
            return
    elif remote is not None:
        raise ValueError('Automation ID already exists without sync record; refusing update')
    else:
        # Guard against an earlier manual automation with the same name but a different ID.
        states = request(token, 'GET', '/states')
        if not isinstance(states, list):
            raise ValueError('Could not inspect existing automations; no changes made')
        if any(isinstance(s, dict) and s.get('entity_id', '').startswith('automation.')
               and s.get('attributes', {}).get('friendly_name') == ALIAS for s in states):
            raise ValueError('An automation with the same name already exists; refusing duplicate')
    backup(remote)   # A failed backup aborts BEFORE a remote write.
    request(token, 'POST', path, automation)
    # Home Assistant's automation config editor persists and reloads the automation.
    # Verify by reading back; never command the Shelly directly from this agent.
    for _ in range(3):
        verified = request(token, 'GET', path, missing_ok=True)
        if isinstance(verified, dict) and verified.get('id') == AUTOMATION_ID \
                and verified.get('alias') == ALIAS:
            break
        time.sleep(1)
    else:
        raise ValueError('Automation save could not be verified; investigate before retrying')
    save_record(source_sha, verified)
    print('[pixar-automation] Lenovo charging automation deployed and verified', flush=True)
