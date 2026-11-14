# Regenera el audio de prueba (voz sintética en español, WAV 16 kHz mono) con la síntesis de Windows.
# Uso: powershell -File tests/fixtures/make_speech.ps1
Add-Type -AssemblyName System.Speech
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$text = Get-Content -Raw -Encoding UTF8 (Join-Path $here "speech_es.txt")
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'es-*' } | Select-Object -First 1
if (-not $v) { throw "No hay ninguna voz en español instalada" }
$s.SelectVoice($v.VoiceInfo.Name)
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile((Join-Path $here "speech_es.wav"), $fmt)
$s.Speak($text)
$s.Dispose()
