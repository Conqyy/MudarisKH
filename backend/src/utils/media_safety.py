"""Input restrictions shared by media conversion and transcription."""

# File bytes must decode as media. Playlist/concat demuxers can dereference
# embedded URLs or paths and are deliberately absent from this allowlist.
FFMPEG_INPUT_OPTIONS = [
    "-protocol_whitelist", "file,pipe",
    "-format_whitelist", "mp3,wav,flac,ogg,aac,mov,mp4,m4a,3gp,3g2,mj2,matroska,webm",
]
