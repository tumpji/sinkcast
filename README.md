# sinkcast

Stream your Linux PC's audio (PipeWire/PulseAudio) to any Chromecast / Google Cast device.

## Install

    ./install.sh    # audio tools + Python venv + `sinkcast` command in ~/.local/bin

## Use

    sinkcast --list               # show devices on the network
    sinkcast -d "living room"     # stream to a device (name, UUID or IP; -d optional if there's only one)
    sinkcast -d kitchen -c mp3    # codec: flac (default, lossless), wav, mp3 (320 kbps)

Ctrl+C stops and restores your audio output. With `--keep-default` the system output is left
alone and you route apps to the "Cast: …" output yourself. The device must reach this PC on
TCP port 5000 (`-p` to change), so allow it in your firewall if needed.
