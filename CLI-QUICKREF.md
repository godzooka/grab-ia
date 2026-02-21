# grab-IA CLI Quick Reference

## Essential Commands

### Start New Job
```bash
python grabia_cli.py start --items items.txt --output ./downloads
```

### Resume Job
```bash
python grabia_cli.py resume --output ./downloads
```

### Check Status
```bash
python grabia_cli.py status --output ./downloads
```

## Common Patterns

### High-Performance Download
```bash
python grabia_cli.py start \
  --items items.txt \
  --output ./downloads \
  --workers 16 \
  --dynamic
```

### Bandwidth-Limited Download
```bash
python grabia_cli.py start \
  --items items.txt \
  --output ./downloads \
  --workers 8 \
  --speed-limit 10  
```

### Music Collection (MP3/FLAC only)
```bash
python grabia_cli.py start \
  --items music_items.txt \
  --output ./music \
  --extensions mp3,flac,m4a \
  --workers 12
```

### Book Collection (PDF/EPUB only)
```bash
python grabia_cli.py start \
  --items books.txt \
  --output ./books \
  --extensions pdf,epub,mobi \
  --workers 8
```

### Video Collection (MP4/MKV only)
```bash
python grabia_cli.py start \
  --items videos.txt \
  --output ./videos \
  --extensions mp4,mkv,avi \
  --workers 4 \
  --speed-limit 50
```

### Metadata-Only Harvest
```bash
python grabia_cli.py start \
  --items items.txt \
  --output ./metadata \
  --metadata-only \
  --workers 16
```

### Sync Mode (Skip Existing)
```bash
python grabia_cli.py start \
  --items items.txt \
  --output ./downloads \
  --sync \
  --workers 8
```

### Verbose Logging
```bash
python grabia_cli.py start \
  --items items.txt \
  --output ./downloads \
  --verbose
```

### Regex Filter (Live Recordings)
```bash
python grabia_cli.py start \
  --items concerts.txt \
  --output ./concerts \
  --filter ".*live.*\\.mp3$" \
  --workers 8
```

## All Options

### start
| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--items` | path | Required | Item list (TXT/CSV) |
| `--output` | path | Required | Output directory |
| `--workers` | int | 8 | Max workers (1-64) |
| `--speed-limit` | int | 0 | MB/s (0=unlimited) |
| `--sync` | flag | False | Skip existing files |
| `--dynamic` | flag | False | Dynamic scaling |
| `--metadata-only` | flag | False | Metadata only |
| `--filter` | regex | None | Filename pattern |
| `--extensions` | csv | None | File extensions |
| `--verbose` | flag | False | Detailed logs |

### resume
| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--output` | path | Required | Existing job directory |
| `--workers` | int | 8 | Max workers |
| `--speed-limit` | int | 0 | MB/s (0=unlimited) |
| `--sync` | flag | False | Skip existing files |
| `--dynamic` | flag | False | Dynamic scaling |
| `--metadata-only` | flag | False | Metadata only |
| `--filter` | regex | None | Filename pattern |
| `--extensions` | csv | None | File extensions |
| `--verbose` | flag | False | Detailed logs |

### status
| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--output` | path | Required | Job directory to check |

## Progress Indicators

### Normal Mode
```
📊 Progress: 45.2% [123/272 files]
⚡ Speed: 8.4 MB/s
👷 Workers: 8/8 active
📦 Queue: 45 pending
❌ Failed: 2
⏱️  ETA: 15m 34s
```

### Verbose Mode
Shows live logs with timestamps:
```
[14:23:45] [INFO] Scanning: item_id_1
[14:23:46] [SUCCESS] ✓ Downloaded: file1.mp3
[14:23:47] [INFO] Scanning: item_id_2
[14:23:48] [SUCCESS] 📄 Generated README for item_id_2
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (file not found, invalid args, etc.) |
| 2 | Keyboard interrupt (Ctrl+C) |

## Tips & Tricks

### Background Execution
```bash
# Linux/macOS
nohup python grabia_cli.py start --items items.txt --output ./downloads > output.log 2>&1 &

# Check progress
tail -f output.log

# Or use screen/tmux
screen -S grabia
python grabia_cli.py start --items items.txt --output ./downloads
# Detach: Ctrl+A, then D
# Reattach: screen -r grabia
```

### Multiple Jobs
```bash
# Run different jobs in parallel
python grabia_cli.py start --items music.txt --output ./music &
python grabia_cli.py start --items books.txt --output ./books &
python grabia_cli.py start --items videos.txt --output ./videos &
```

### Scheduled Downloads (cron)
```bash
# Add to crontab (crontab -e)
0 2 * * * cd /path/to/grab-ia && python grabia_cli.py resume --output ./downloads
```

### Resume After Crash
```bash
# Just use resume - it picks up exactly where it left off
python grabia_cli.py resume --output ./downloads
```

### Switch from GUI to CLI
```bash
# Start in GUI, then close GUI and resume in CLI
python grabia_cli.py resume --output ./downloads --verbose
```

### Incremental Sync
```bash
# Download new items, skip existing
python grabia_cli.py start \
  --items updated_list.txt \
  --output ./downloads \
  --sync \
  --workers 16
```

## Troubleshooting

### Check if job is running
```bash
python grabia_cli.py status --output ./downloads
```

### View last 50 log lines
```bash
tail -50 grabia_debug.log
```

### Test with single item
```bash
echo "item_id" > test.txt
python grabia_cli.py start --items test.txt --output ./test --verbose
```

### Reset failed files
Delete the database and restart:
```bash
rm downloads/grabia_state.db
python grabia_cli.py start --items items.txt --output ./downloads
```

## Performance Tuning

### Fast Network (Gigabit)
```bash
--workers 16 --dynamic
```

### Slow Network (DSL)
```bash
--workers 4 --speed-limit 5
```

### Rate Limited (Frequent 429)
```bash
--workers 4 --dynamic
# Dynamic scaling will back off automatically
```

### Large Files (>1GB)
```bash
--workers 4
# Fewer workers to avoid memory pressure
```

### Small Files (<10MB)
```bash
--workers 16 --dynamic
# More workers for better concurrency
```

## Docker Equivalents

### CLI to Docker
```bash
# CLI
python grabia_cli.py start --items items.txt --output ./downloads --workers 8

# Docker equivalent
docker run -v $(pwd)/downloads:/downloads -v $(pwd)/items:/items \
  grab-ia:latest start --items /items/items.txt --output /downloads --workers 8
```

### Resume in Docker
```bash
docker run -v $(pwd)/downloads:/downloads \
  grab-ia:latest resume --output /downloads --workers 8
```

## Advanced Usage

### Custom Filter Examples
```bash
# Only files from 2023
--filter ".*2023.*"

# Only live recordings
--filter ".*live.*\\.flac$"

# Only specific directories
--filter "^subdir/.*\\.pdf$"

# Case insensitive (use (?i))
--filter "(?i).*concert.*"
```

### Extension Combinations
```bash
# Audio files
--extensions mp3,flac,m4a,ogg,wav

# Documents
--extensions pdf,epub,mobi,txt,doc,docx

# Video files
--extensions mp4,mkv,avi,mov,webm

# Images
--extensions jpg,png,gif,tiff,bmp

# Archives
--extensions zip,tar,gz,7z,rar
```
