import io
import json
import time
import wave
from unittest.mock import Mock

from fastapi.testclient import TestClient

from api.audio import AudioHub, MAX_AUDIO_BYTES
from app import app


def test_audio_api_upload_play_and_validation(monkeypatch, tmp_path):
    sdk = Mock()
    sdk._Call.return_value = (0, '{"audio_list": []}')
    vui = Mock()
    vui.GetVolume.return_value = (0, 6)
    vui.SetVolume.return_value = 0
    monkeypatch.setattr(app.state, "audio", AudioHub(sdk, tmp_path, vui))
    client = TestClient(app)
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav:
        wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\0' * 64000)
    result = client.post('/api/audio/upload?name=test', content=buffer.getvalue(), headers={'Content-Type': 'audio/wav'})
    assert result.status_code == 200
    unique_id = result.json()['unique_id']
    assert next(tmp_path.glob(f'{unique_id}_*.wav')).read_bytes() == buffer.getvalue()
    assert result.json()['audio_list'][0]['CUSTOM_NAME'] == 'test'
    assert result.json()['audio_list'][0]['DURATION'] == 2
    assert not sdk._Call.called
    for data, status in [(b'not wav', 422), (buffer.getvalue()[:-2], 422), (b'x' * (MAX_AUDIO_BYTES + 1), 413)]:
        assert client.post('/api/audio/upload?name=test', content=data).status_code == status
    assert client.post('/api/audio/upload?name=../test', content=buffer.getvalue()).status_code == 422
    assert client.post('/api/audio/play', json={'unique_id': 'bad'}).status_code == 422
    payload = {'unique_id': unique_id}
    played = client.post('/api/audio/play', json=payload)
    assert played.status_code == 200 and played.json()['backend'] == 'megaphone'
    deadline = time.monotonic() + 1
    while sdk._Call.call_count < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    upload = next(call for call in sdk._Call.call_args_list if call.args[0] == 4003)
    assert json.loads(upload.args[1])['current_block_index'] == 1
    assert client.post('/api/audio/pause').status_code == 200
    assert any(call.args[0] == 4002 for call in sdk._Call.call_args_list)
    assert client.post('/api/audio/play', json=payload, headers={'Origin': 'https://other.example'}).status_code == 403
    sdk._Call.return_value = (3104, '')
    sdk.reset_mock()
    assert client.post('/api/audio/play', json={'unique_id': 'bb07b3b9-2d82-4785-b6b5-4c9319bf93f4'}).status_code == 503
    assert sdk._Call.call_count == 1  # No replay on an uncertain result.
    assert client.get('/api/audio/volume').json() == {'volume': 6}
    assert client.post('/api/audio/volume', json={'volume': 8}).json() == {'code': 0, 'volume': 8}
    vui.SetVolume.assert_called_once_with(8)
    assert client.post('/api/audio/volume', json={'volume': 11}).status_code == 422
    assert client.delete(f'/api/audio/{unique_id}').status_code == 200
    assert not next(tmp_path.glob(f'{unique_id}_*.wav'), None)
