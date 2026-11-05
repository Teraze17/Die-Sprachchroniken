"""Offline German WAV generation with an installed Windows SAPI/System.Speech voice.

No web request, AI API, speech recognition, or voice-channel connection.
On Linux deployments, replace this optional backend with a local Piper voice.
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


def synthesize_german(text: str) -> Path:
    if sys.platform != "win32":
        raise RuntimeError("本機聽力語音目前支援 Windows；Linux 雲端版需改用 Piper 離線德語語音模型。")
    if not isinstance(text, str) or not text.strip() or len(text) > 1000:
        raise RuntimeError("聽力內容格式不正確。")
    out = Path(tempfile.gettempdir()) / f"sprachchroniken_{uuid.uuid4().hex}.wav"
    # PowerShell 5.1, .NET Framework System.Speech (not a network service).
    ps_text = text.replace("'", "''")
    ps_path = str(out).replace("'", "''")
    script = f"""
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Speech
$synth=New-Object System.Speech.Synthesis.SpeechSynthesizer
try {{
  $voice=$synth.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -like 'de-*' }} | Select-Object -First 1
  if ($null -eq $voice) {{ throw 'NO_GERMAN_VOICE' }}
  $synth.SelectVoice($voice.VoiceInfo.Name)
  $synth.Rate=-1
  $synth.SetOutputToWaveFile('{ps_path}')
  $synth.Speak('{ps_text}')
  $synth.SetOutputToNull()
}} finally {{ $synth.Dispose() }}
"""
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True, timeout=25, check=False,
        )
        if result.returncode != 0 or not out.is_file() or out.stat().st_size < 100:
            if b"NO_GERMAN_VOICE" in result.stderr or b"NO_GERMAN_VOICE" in result.stdout:
                raise RuntimeError("找不到可用的 Windows 德語 SAPI 語音。請到 Windows 設定安裝 Deutsch (Deutschland) 的 Text-to-Speech 語音。")
            raise RuntimeError("Windows 德語語音合成未成功。請確認已安裝德語文字轉語音（SAPI）語音包。")
        return out
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("本機語音合成逾時，請確認 Windows 德語語音包。") from exc
    finally:
        if not out.is_file() or out.stat().st_size < 100:
            out.unlink(missing_ok=True)
