# grab-IA

A thread-safe, resilient downloader for Internet Archive items with GUI, CLI, and Docker support.

 <p align="center">
  <img src="img/grab-IA_GUI.png" alt="grab-IA Dashboard" width="700">
</p>

![Version](https://img.shields.io/badge/version-2.0.0-blue)
![Python](https://img.shields.io/badge/python-3.8+-green)
![License](https://img.shields.io/badge/license-MIT-orange)

## Features

- **🖥️ Multiple Interfaces**: GUI, CLI, or headless Docker
- **🔄 Resume Support**: Seamlessly switch between GUI and CLI
- **⚡ High Performance**: Multi-threaded downloads with dynamic scaling
- **🛡️ Robust**: MD5 verification, byte-level resume, global backoff
- **🎯 Flexible Filtering**: Regex patterns, extension whitelists, metadata-only mode
- **💾 Persistent State**: SQLite database tracks all downloads
- **🚀 Production Ready**: Docker support for servers and Kubernetes

## Quick Start

### GUI Mode (Recommended for Desktop)

#### Windows
```bash
# Double-click launch.bat
launch.bat
```

#### Linux/macOS
```bash
chmod +x launch.sh
./launch.sh
```

### CLI Mode (Recommended for Servers)

```bash
# Start a new job
python grabia_cli.py start --items items.txt --output ./downloads --workers 8

# Resume existing job
python grabia_cli.py resume --output ./downloads

# Check status
python grabia_cli.py status --output ./downloads
```

### Docker (Recommended for Production)

```bash
# Build image
docker build -t grab-ia .

# Run download job
docker run -it --rm \
  -v $(pwd)/downloads:/downloads \
  -v $(pwd)/items:/items \
  grab-ia:latest \
  start --items /items/items.txt --output /downloads --workers 8
```

## Installation

### Prerequisites
- Python 3.8 or higher
- Internet connection

### Method 1: Automated (Recommended)
The launcher scripts automatically create a virtual environment and install dependencies.

**No manual installation needed!** Just run `launch.bat` (Windows) or `./launch.sh` (Linux/macOS).

### Method 2: Manual
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt
```

### Method 3: pip install (Coming Soon)
```bash
pip install grab-ia
```

## Usage

### GUI Interface

1. **Load Item List**: Browse for a TXT or CSV file with Archive.org identifiers
2. **Set Output Directory**: Choose download destination
3. **Configure Options**:
   - Max workers: Concurrent downloads (1-64)
   - Speed limit: Bandwidth cap in MB/s
   - Sync mode: Skip existing files
   - Dynamic scaling: Auto-adjust workers
   - Metadata only: Download only metadata
4. **Start**: Click START and monitor progress

### CLI Interface

#### Start New Job
```bash
python grabia_cli.py start \
  --items items.txt \
  --output ./downloads \
  --workers 16 \
  --speed-limit 50 \
  --sync \
  --dynamic
```

#### Resume Job (works with GUI jobs too!)
```bash
python grabia_cli.py resume \
  --output ./downloads \
  --workers 8
```

#### Check Status
```bash
python grabia_cli.py status --output ./downloads
```

#### Advanced Filtering
```bash
# Download only MP3 and FLAC files
python grabia_cli.py start \
  --items items.txt \
  --output ./downloads \
  --extensions mp3,flac

# Use regex filter
python grabia_cli.py start \
  --items items.txt \
  --output ./downloads \
  --filter ".*live.*\\.mp3$"

# Metadata only
python grabia_cli.py start \
  --items items.txt \
  --output ./downloads \
  --metadata-only
```

#### Verbose Output
```bash
python grabia_cli.py start \
  --items items.txt \
  --output ./downloads \
  --verbose
```

### Docker Deployment

See [DOCKER.md](DOCKER.md) for comprehensive Docker documentation.

#### Quick Examples

**Headless download:**
```bash
docker run -d \
  -v $(pwd)/downloads:/downloads \
  -v $(pwd)/items:/items \
  grab-ia:latest \
  start --items /items/items.txt --output /downloads --workers 8
```

**With Docker Compose:**
```bash
docker-compose up -d grab-ia-cli
docker-compose logs -f grab-ia-cli
```

**Resume in Docker:**
```bash
docker run -it --rm \
  -v $(pwd)/downloads:/downloads \
  grab-ia:latest \
  resume --output /downloads
```

## Architecture

### Core Components

- **grabia_core.py**: Thread-safe download engine with SQLite persistence
- **grabia_gui.py**: PySide6 GUI with live metrics and log viewer
- **grabia_cli.py**: Command-line interface with progress monitoring
- **launch.py**: Cross-platform launcher with automatic setup


The core engine implements battle-tested patterns:

- **PROT-001**: Atomic Safe-Swap with MD5 verification
- **PROT-002**: Global Backoff Coordination for rate limiting
- **PROT-003**: Byte-Level Resume (HTTP 206 Range requests)
- **ASSET-009**: Token-Bucket Rate Limiting
- **ASSET-015**: Recursive Path Governance
- **ASSET-022**: Dynamic Worker Scaling
- **PERSISTENCE-001**: SQLite WAL for concurrent access

### State Management

All interfaces (GUI and CLI) share the same SQLite database:

```
downloads/
├── grabia_state.db       # Shared state database
├── item_id_1/
│   ├── README.txt        # Auto-generated metadata
│   ├── file1.mp3
│   └── file2.pdf
└── item_id_2/
    └── ...
```

You can **start in GUI, stop, and resume in CLI** (or vice versa). The state is always preserved.

## Configuration

### GUI Settings

All settings are available in the GUI sidebar:
- Item list (TXT/CSV)
- Output directory
- Auth/credentials (optional)
- Filename regex filter
- Extension whitelist
- Max workers
- Speed limit
- Sync mode
- Dynamic scaling
- Metadata only

### CLI Options

```bash
python grabia_cli.py start --help
```

| Option | Description | Default |
|--------|-------------|---------|
| `--items` | Path to items list (TXT/CSV) | Required |
| `--output` | Output directory | Required |
| `--workers` | Max concurrent workers | 8 |
| `--speed-limit` | Bandwidth limit (MB/s, 0=unlimited) | 0 |
| `--sync` | Skip existing files | False |
| `--dynamic` | Enable dynamic scaling | False |
| `--metadata-only` | Download metadata only | False |
| `--filter` | Filename regex pattern | None |
| `--extensions` | Comma-separated extensions | None |
| `--verbose` | Show detailed logs | False |

### Environment Variables (Docker)

| Variable | Description | Default |
|----------|-------------|---------|
| `OUTPUT_DIR` | Default output directory | `/downloads` |

## Item List Format

### TXT Format (Simple)
```
item_identifier_1
item_identifier_2
item_identifier_3
```

### CSV Format (With Metadata)
```csv
identifier
item_id_1
item_id_2
item_id_3
```

## Features in Detail

### Intelligent Resume
- Downloads resume from exact byte position
- Works across restarts and crashes
- MD5 verification ensures integrity
- Seamless GUI ↔ CLI switching

### Dynamic Scaling
- Starts with 1 worker
- Scales up after 5 consecutive successes
- Scales down immediately on failure
- Respects `--workers` maximum

### Global Backoff
- Coordinates across all workers
- Triggers on 429 (rate limit) or 503 (server error)
- Random backoff: 30-60 seconds
- Prevents thundering herd

### Bandwidth Control
- Token-bucket algorithm
- Smooth rate limiting
- Per-byte throttling
- No burst spikes

### Filtering
- **Regex**: Match filenames with patterns
- **Extensions**: Whitelist specific types
- **Anti-clutter**: Auto-skip system files
- **Metadata-only**: Just README/XML/JSON

## Monitoring

### GUI Metrics
- Queue depth
- Active workers
- Download speed
- Progress percentage
- Failed files
- Real-time logs

### CLI Progress
```
📊 Progress: 45.2% [123/272 files]
⚡ Speed: 8.4 MB/s
👷 Workers: 8/8 active
📦 Queue: 45 pending
❌ Failed: 2
⏱️  ETA: 15m 34s
```

### Docker Logs
```bash
docker logs -f <container_id>
```

## Troubleshooting

### Common Issues

#### Python not found
```bash
# Install Python 3.8+
sudo apt install python3 python3-venv  # Ubuntu/Debian
brew install python3                   # macOS
# Windows: Download from python.org
```

#### Permission denied (Linux/macOS)
```bash
chmod +x launch.sh
chmod +x grabia_cli.py
```

#### Virtual environment issues
```bash
# Delete and recreate
rm -rf venv
./launch.sh
```

#### Docker permission denied
```bash
# Add user to docker group
sudo usermod -aG docker $USER
# Log out and back in
```

#### GUI doesn't start in Docker
```bash
# Enable X11 forwarding
xhost +local:docker
docker run -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix ...
```

### Debug Logs

All operations are logged to:
- **GUI**: Live log viewer with severity filtering
- **CLI**: Console output (use `--verbose` for details)
- **File**: `grabia_debug.log` in project directory

## Performance Tuning

### Optimal Worker Count
- **Fast connection**: 8-16 workers
- **Slow connection**: 4-8 workers
- **Rate-limited**: Use dynamic scaling

### Bandwidth Limiting
```bash
# Limit to 50 MB/s
python grabia_cli.py start ... --speed-limit 50
```

### Memory Usage
- ~50MB base overhead
- ~5MB per worker
- Disk I/O is the bottleneck, not RAM

## Production Deployment

### Systemd Service (Linux)
```bash
# See DOCKER.md for full systemd unit file
sudo systemctl enable grab-ia.service
sudo systemctl start grab-ia.service
```

### Docker Compose
```bash
# See docker-compose.yml
docker-compose up -d
```

### Kubernetes
```bash
# See DOCKER.md for Job/CronJob manifests
kubectl apply -f grab-ia-job.yaml
```

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly (GUI, CLI, Docker)
5. Submit a pull request
This project is actively developed; internal refactors may occur between minor versions, but CLI/GUI behavior will remain stable

## License

MIT License - see LICENSE file for details

## Acknowledgments

- Built for the Internet Archive preservation community
- Inspired by archival best practices
- Powered by PySide6, Requests, and SQLite

## Support

- **Issues**: GitHub Issues
- **Documentation**: See `SETUP.md` and `DOCKER.md`
- **Logs**: Check `grabia_debug.log`

---

**grab-IA** - Because digital preservation matters. 🔥
