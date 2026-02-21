#!/usr/bin/env python3
"""
grab-IA CLI Interface
=====================
Full-featured command-line interface compatible with GUI state.

Features:
- Resume jobs started in GUI
- Live progress monitoring
- Full configuration control
- Headless-ready design
"""

import argparse
import sys
import time
import signal
from pathlib import Path
from typing import List

from grabia_core import GrabIACore


def _load_s3_credentials(auth_path: str):
    """
    Load S3 credentials from a file.
    Expects lines like:
        S3_ACCESS_KEY=your_access_key
        S3_SECRET_KEY=your_secret_key
    or shorthand:
        access=your_access_key
        secret=your_secret_key
    Returns (access_key, secret_key) tuple or None.
    """
    if not auth_path:
        return None
    p = Path(auth_path)
    if not p.exists():
        print(f"⚠  Auth file not found: {auth_path}")
        return None
    try:
        creds = {}
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, _, val = line.partition('=')
                creds[key.strip().lower()] = val.strip()
        access = creds.get('s3_access_key') or creds.get('access')
        secret = creds.get('s3_secret_key') or creds.get('secret')
        if access and secret:
            print("✓ Credentials loaded from auth file")
            return (access, secret)
        else:
            print("⚠  Auth file found but missing access/secret keys")
            return None
    except Exception as e:
        print(f"⚠  Failed to read auth file: {e}")
        return None


class GrabIACLI:
    """Command-line interface for grab-IA."""
    
    def __init__(self):
        self.core = None
        self.running = False
        self.last_stats = {}
        
        # Handle Ctrl+C gracefully
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        print("\n🛑 Shutdown signal received, stopping gracefully...")
        if self.core:
            self.core.stop()
        self.running = False
        sys.exit(0)
    
    def _load_identifiers(self, path: str) -> List[str]:
        """Load identifiers from TXT or CSV file."""
        p = Path(path)
        
        if not p.exists():
            print(f"❌ Error: File not found: {path}")
            sys.exit(1)
        
        identifiers = []
        
        if p.suffix.lower() == '.csv':
            import csv
            with open(p, 'r') as f:
                for row in csv.reader(f):
                    if row:
                        identifiers.append(row[0].strip())
        else:
            identifiers = [
                line.strip() 
                for line in p.read_text().splitlines() 
                if line.strip()
            ]
        
        return identifiers
    
    def _print_header(self):
        """Print CLI header."""
        print("=" * 70)
        print("🔥 grab-IA - Internet Archive Downloader")
        print("=" * 70)
        print()
    
    def _print_stats(self, stats: dict):
        """Print current statistics."""
        # Clear previous lines (ANSI escape codes)
        if self.last_stats:
            print("\033[F" * 6, end="")  # Move cursor up 6 lines
        
        print(f"📊 Progress: {stats['percent_complete']:.1f}% "
              f"[{stats['items_done']}/{stats['total_files']} files]")
        print(f"⚡ Speed: {stats['current_speed_mbps'] / 8:.1f} MB/s")
        print(f"👷 Workers: {stats['target_workers']}/{stats['active_threads']} active")
        print(f"📦 Queue: {stats['queue_depth']} pending")
        print(f"❌ Failed: {stats['failed_files']}")
        
        # ETA calculation
        eta_seconds = stats.get('eta_seconds', 0)
        if eta_seconds > 0:
            eta_mins = int(eta_seconds / 60)
            eta_secs = int(eta_seconds % 60)
            print(f"⏱️  ETA: {eta_mins}m {eta_secs}s")
        else:
            print("⏱️  ETA: Calculating...")
        
        self.last_stats = stats
    
    def _monitor_progress(self, verbose: bool = False):
        """Monitor download progress."""
        print("\n📡 Monitoring progress (Ctrl+C to stop)...\n")
        
        last_log_index = 0
        
        while self.running:
            try:
                stats = self.core.get_stats()
                
                # Print stats
                self._print_stats(stats)
                
                # Verbose logging
                if verbose:
                    logs, last_log_index = self.core.get_logs(last_log_index)
                    for log in logs:
                        print(f"\033[K{log}")  # Clear line before printing
                
                # Check if job finished
                if (not stats['scanner_active'] and 
                    stats['queue_depth'] == 0 and
                    stats['items_done'] + stats['failed_files'] >= stats['total_files'] and
                    stats['total_files'] > 0):
                    self.running = False
                    break
                
                time.sleep(0.5)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"\n❌ Monitoring error: {e}")
                break
        
        # Final summary
        print("\n" + "=" * 70)
        print("✅ JOB COMPLETE")
        print("=" * 70)
        final_stats = self.core.get_stats()
        print(f"Items scanned: {final_stats['scanned_ids']}")
        print(f"Files downloaded: {final_stats['items_done']}")
        print(f"Files failed: {final_stats['failed_files']}")
        print(f"Total bytes: {final_stats['total_bytes_downloaded'] / (1024**3):.2f} GB")
        print("=" * 70)
    
    def start(self, args):
        """Start a new download job."""
        self._print_header()
        
        # Load identifiers
        print(f"📂 Loading identifiers from: {args.items}")
        identifiers = self._load_identifiers(args.items)
        print(f"✓ Loaded {len(identifiers)} identifiers")
        
        # Parse extension whitelist
        extensions = None
        if args.extensions:
            extensions = [e.strip() for e in args.extensions.split(',')]
            print(f"✓ Extension filter: {extensions}")
        
        # Initialize core
        print(f"⚙️  Initializing engine...")
        print(f"   Output directory: {args.output}")
        print(f"   Max workers: {args.workers}")
        print(f"   Speed limit: {args.speed_limit} MB/s" if args.speed_limit > 0 else "   Speed limit: Unlimited")
        print(f"   Sync mode: {'ON' if args.sync else 'OFF'}")
        print(f"   Dynamic scaling: {'ON' if args.dynamic else 'OFF'}")
        print(f"   Metadata only: {'ON' if args.metadata_only else 'OFF'}")

        s3_credentials = _load_s3_credentials(getattr(args, 'auth', None))
        if s3_credentials:
            print("   Auth: ✓ Credentials loaded")
        else:
            print("   Auth: None (public access)")

        self.core = GrabIACore(
            output_dir=args.output,
            max_workers=args.workers,
            speed_limit_bps=args.speed_limit * 1024 * 1024,
            sync_mode=args.sync,
            filter_regex=args.filter if args.filter else None,
            extension_whitelist=extensions,
            dynamic_scaling=args.dynamic,
            metadata_only=args.metadata_only,
            s3_credentials=s3_credentials
        )
        
        # Start job
        print("\n🚀 Starting download job...")
        self.core.start(identifiers)
        self.running = True
        
        # Monitor progress
        self._monitor_progress(verbose=args.verbose)
        
        # Cleanup
        self.core.stop()
    
    def resume(self, args):
        """Resume an existing job."""
        self._print_header()
        
        print(f"🔄 Resuming job in: {args.output}")
        
        # Check for existing database
        db_path = Path(args.output) / "grabia_state.db"
        if not db_path.exists():
            print("❌ Error: No existing job found in this directory")
            print("   Tip: Use 'start' to begin a new job")
            sys.exit(1)
        
        print("✓ Found existing job database")
        
        # Parse extension whitelist
        extensions = None
        if args.extensions:
            extensions = [e.strip() for e in args.extensions.split(',')]
        
        # Initialize core (will read from existing DB)
        print("⚙️  Initializing engine...")
        s3_credentials = _load_s3_credentials(getattr(args, 'auth', None))
        if s3_credentials:
            print("   Auth: ✓ Credentials loaded")
        else:
            print("   Auth: None (public access)")
        self.core = GrabIACore(
            output_dir=args.output,
            max_workers=args.workers,
            speed_limit_bps=args.speed_limit * 1024 * 1024,
            sync_mode=args.sync,
            filter_regex=args.filter if args.filter else None,
            extension_whitelist=extensions,
            dynamic_scaling=args.dynamic,
            metadata_only=args.metadata_only,
            s3_credentials=s3_credentials
        )
        
        # Get pending items from database
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT DISTINCT item_id FROM files WHERE status != 'done'")
        pending_items = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        if not pending_items:
            print("✓ No pending items found - job already complete!")
            return
        
        print(f"✓ Found {len(pending_items)} items with pending files")
        
        # Resume job
        print("\n🚀 Resuming download job...")
        self.core.start(pending_items)
        self.running = True
        
        # Monitor progress
        self._monitor_progress(verbose=args.verbose)
        
        # Cleanup
        self.core.stop()
    
    def status(self, args):
        """Show status of an existing job."""
        self._print_header()
        
        db_path = Path(args.output) / "grabia_state.db"
        if not db_path.exists():
            print("❌ No job found in this directory")
            sys.exit(1)
        
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        
        # Get statistics
        total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        done = conn.execute("SELECT COUNT(*) FROM files WHERE status = 'done'").fetchone()[0]
        failed = conn.execute("SELECT COUNT(*) FROM files WHERE status = 'failed'").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM files WHERE status = 'pending'").fetchone()[0]
        retrying = conn.execute("SELECT COUNT(*) FROM files WHERE status = 'retrying'").fetchone()[0]
        
        items = conn.execute("SELECT COUNT(DISTINCT item_id) FROM files").fetchone()[0]
        
        conn.close()
        
        print(f"📊 Job Status: {args.output}")
        print("=" * 70)
        print(f"Items: {items}")
        print(f"Total files: {total}")
        print(f"✅ Completed: {done} ({done/total*100:.1f}%)" if total > 0 else "✅ Completed: 0")
        print(f"⏳ Pending: {pending}")
        print(f"🔄 Retrying: {retrying}")
        print(f"❌ Failed: {failed}")
        print("=" * 70)
        
        if pending + retrying > 0:
            print("\n💡 Tip: Use 'grabia_cli.py resume' to continue this job")


def main():
    parser = argparse.ArgumentParser(
        description="grab-IA - Internet Archive Downloader CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start new job
  python grabia_cli.py start --items items.txt --output ./downloads

  # Resume existing job (shares state with GUI)
  python grabia_cli.py resume --output ./downloads

  # Check job status
  python grabia_cli.py status --output ./downloads

  # Start with filters
  python grabia_cli.py start --items items.txt --output ./downloads \\
    --extensions mp3,flac --workers 16 --speed-limit 10

  # Metadata only mode
  python grabia_cli.py start --items items.txt --output ./downloads \\
    --metadata-only
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # START command
    start_parser = subparsers.add_parser('start', help='Start new download job')
    start_parser.add_argument('--items', required=True, help='Path to items list (TXT/CSV)')
    start_parser.add_argument('--output', required=True, help='Output directory')
    start_parser.add_argument('--workers', type=int, default=8, help='Max workers (default: 8)')
    start_parser.add_argument('--speed-limit', type=int, default=0, help='Speed limit in MB/s (0=unlimited)')
    start_parser.add_argument('--sync', action='store_true', help='Skip existing files')
    start_parser.add_argument('--dynamic', action='store_true', help='Enable dynamic scaling')
    start_parser.add_argument('--metadata-only', action='store_true', help='Download metadata only')
    start_parser.add_argument('--filter', help='Filename regex filter')
    start_parser.add_argument('--extensions', help='Comma-separated extensions (e.g., mp3,pdf)')
    start_parser.add_argument('--auth', help='Path to auth/env file with S3_ACCESS_KEY and S3_SECRET_KEY')
    start_parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed logs')
    
    # RESUME command
    resume_parser = subparsers.add_parser('resume', help='Resume existing job')
    resume_parser.add_argument('--output', required=True, help='Output directory with existing job')
    resume_parser.add_argument('--workers', type=int, default=8, help='Max workers (default: 8)')
    resume_parser.add_argument('--speed-limit', type=int, default=0, help='Speed limit in MB/s (0=unlimited)')
    resume_parser.add_argument('--sync', action='store_true', help='Skip existing files')
    resume_parser.add_argument('--dynamic', action='store_true', help='Enable dynamic scaling')
    resume_parser.add_argument('--metadata-only', action='store_true', help='Download metadata only')
    resume_parser.add_argument('--filter', help='Filename regex filter')
    resume_parser.add_argument('--extensions', help='Comma-separated extensions')
    resume_parser.add_argument('--auth', help='Path to auth/env file with S3_ACCESS_KEY and S3_SECRET_KEY')
    resume_parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed logs')
    
    # STATUS command
    status_parser = subparsers.add_parser('status', help='Show job status')
    status_parser.add_argument('--output', required=True, help='Output directory with existing job')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    cli = GrabIACLI()
    
    if args.command == 'start':
        cli.start(args)
    elif args.command == 'resume':
        cli.resume(args)
    elif args.command == 'status':
        cli.status(args)


if __name__ == "__main__":
    main()
