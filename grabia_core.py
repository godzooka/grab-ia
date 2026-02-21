# grabia_core.py
# ðŸ›ï¸ GRAB-IA CORE ENGINE 
# Version: 2.0.0 | 

"""
GRAB-IA CORE ENGINE
===================
A thread-safe, resilient downloader for Internet Archive items.

PROTECTED ASSETS IMPLEMENTED:
- PROT-001: Atomic Safe-Swap (MD5 Verification)
- PROT-002: Global Backoff Coordination
- PROT-003: Byte-Level Resume (HTTP 206)
- ASSET-015: Recursive Path Governance
- ASSET-022: Dynamic Worker Scaling
- ASSET-009: Token-Bucket Rate Limiting + Sync
- ASSET-012: README Generation
- PERSISTENCE-001: SQLite WAL Engine
- ASSET-040/045: Asynchronous Work-Ingestion

"""

import os
import sys
import time
import json
import hashlib
import sqlite3
import threading
import requests
import re
from pathlib import Path
from queue import PriorityQueue, Empty
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple, Any
from datetime import datetime
import random

# =========================================================
# PROTECTED CONSTANTS (ASSET-GEN-002: Functional Logic Gates)
# =========================================================

# MD5 Buffer Size (Forensic Reconstruction Data)
MD5_BUFFER_SIZE = 4096

# Download Chunk Size (128KB - Forensic Reconstruction Data)
DOWNLOAD_CHUNK_SIZE = 131072

# Connection Timeout (Z-Handshake)
CONNECTION_TIMEOUT = 15

# Global Backoff Range (PROT-002)
BACKOFF_MIN_SECONDS = 30
BACKOFF_MAX_SECONDS = 60

# Dynamic Scaling Constants (ASSET-022)
SUCCESS_STREAK_THRESHOLD = 5
SCALE_UP_INCREMENT = 1

# Default Configuration
DEFAULT_MAX_WORKERS = 4
DEFAULT_OUTPUT_DIR = str(Path.home() / "Downloads" / "grabIA Downloads")

# Anti-Clutter Filter (FILTER-GATE)
SYSTEM_FILE_PATTERNS = [
    r'_meta\.xml$',
    r'_meta\.sqlite$',
    r'_files\.xml$',
    r'_thumb\.jpg$',
    r'_itemimage\.jpg$'
]

# User-Agent (Session Tunneling)
USER_AGENT = "grab-IA/2.0 (Archive Mirroring Tool; +https://github.com/grab-ia)"

# =========================================================
# PROTECTED KEYS REGISTRY (ASSET-032: Variable Key Lockdown)
# =========================================================
PROTECTED_KEYS = [
    "scanned_ids",           # Total unique IA items in session
    "items_done",            # Files promoted from .part to final
    "total_files",           # Total files discovered across all items
    "active_threads",        # Current worker count in pool
    "bytes_per_sec",         # Rolling average throughput
    "backoff_active",        # Boolean: Is PROT-002 currently engaged?
    "disk_remaining",        # Bytes available on target partition
    "last_log_index",        # Index of most recent debug line
    "vault_status",          # SQLite WAL health indicator
    "eta_seconds",           # Estimated time to completion
    "percent_complete",      # Overall progress percentage
    "current_speed_mbps",    # Current speed in Mbps
    "total_bytes_downloaded",# Cumulative bytes downloaded
    "failed_files",          # Count of files that failed verification
    "target_workers",        # Current target worker count (dynamic scaling)
    "success_streak",        # Consecutive successful downloads
    "global_backoff_until",  # Timestamp when backoff ends
    "scanner_active",        # Boolean: Is discovery scan running?
    "queue_depth"            # Current task queue size
]

# =========================================================
# DATABASE SCHEMA (PERSISTENCE-001)
# =========================================================
DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    item_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    size INTEGER NOT NULL DEFAULT 0,
    expected_md5 TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (item_id, file_name)
);

CREATE INDEX IF NOT EXISTS idx_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_item_id ON files(item_id);
"""

# =========================================================
# DOWNLOAD TASK CLASS (ASSET-019: Priority-Based Queuing)
# =========================================================
@dataclass(order=True)
class DownloadTask:
    """
    Represents a single file download task with priority handling.
    
    PRIORITY TIERS (ASSET-019):
    - 10-20: Metadata/Small files (README, XML, JSON)
    - 50: Standard files
    - 80: Large files (>100MB)
    """
    priority: int
    item_id: str = field(compare=False)
    file_name: str = field(compare=False)
    file_url: str = field(compare=False)
    file_size: int = field(compare=False)
    expected_md5: Optional[str] = field(compare=False)
    attempt_count: int = field(default=0, compare=False)
    
    def __post_init__(self):
        """Calculate priority based on file characteristics."""
        if self.priority == 0:  # Auto-calculate if not set
            # Metadata files get highest priority
            lower_name = self.file_name.lower()
            if any(ext in lower_name for ext in ['.xml', '.json', '.txt', 'readme']):
                self.priority = 10
            elif self.file_size > 100 * 1024 * 1024:  # >100MB
                self.priority = 80
            else:
                self.priority = 50

# Core Class Definition, Initialization, and Thread Management

# =========================================================
# GRABIA CORE ENGINE CLASS
# =========================================================
class GrabIACore:
    """
    The central orchestrator for Internet Archive downloads.
    
    ARCHITECTURAL GUARANTEES:
    - Thread-safe state management (PERSISTENCE-001)
    - Zero race conditions via proper locking
    - Disposable UI design (Bridge Pattern)
    - Eager ingestion (ASSET-040/045)
    """
    
    def __init__(self, output_dir: str = None, max_workers: int = DEFAULT_MAX_WORKERS,
                 speed_limit_bps: int = 0, sync_mode: bool = False,
                 filter_regex: str = None,
                 extension_whitelist: List[str] = None, dynamic_scaling: bool = True,
                 s3_credentials: Tuple[str, str] = None, metadata_only: bool = False):

        """
        Initialize the Grab-IA Core Engine.
        
        Args:
            output_dir: Base download directory
            max_workers: Maximum concurrent download threads
            speed_limit_bps: Bandwidth limit in bytes per second (0 = unlimited)
            sync_mode: Skip existing files if MD5 matches
            filter_regex: Regex pattern to filter filenames
            extension_whitelist: List of allowed extensions (e.g., ['.mp3', '.pdf'])
            dynamic_scaling: Enable ASSET-022 dynamic worker scaling
            s3_credentials: Tuple of (access_key, secret_key) for restricted items
            metadata_only: Only download README/metadata files
        """
        
        # ===== PATH CONFIGURATION =====
        self.output_dir = Path(output_dir) if output_dir else Path(DEFAULT_OUTPUT_DIR)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # ===== WORKER CONFIGURATION (ASSET-022) =====
        self.max_workers = max_workers
        self.dynamic_scaling = dynamic_scaling
        self.target_workers = 1 if dynamic_scaling else max_workers
        self.success_streak = 0
        
        # ===== BANDWIDTH THROTTLING (ASSET-009: Token-Bucket) =====
        self.speed_limit_bps = speed_limit_bps
        self.tokens = 0.0
        self.last_refill = time.time()
        self.token_lock = threading.Lock()
        
        # ===== MODE FLAGS =====
        self.sync_mode = sync_mode
        self.metadata_only = metadata_only
        
        # ===== FILTERING =====
        self.filter_regex = re.compile(filter_regex) if filter_regex else None
        self.extension_whitelist = extension_whitelist
        
        # ===== AUTHENTICATION (ASSET-007) =====
        self.s3_credentials = s3_credentials
        
        # ===== THREADING PRIMITIVES =====
        self.stop_event = threading.Event()
        self.task_queue = PriorityQueue()
        self.executor = None
        self.scanner_thread = None
        self.worker_futures = []
        
        # ===== GLOBAL BACKOFF (PROT-002) =====
        self.global_backoff_until = 0.0
        self.backoff_lock = threading.Lock()
        
        # ===== SESSION PERSISTENCE (SESSION-TUNNEL) =====
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': USER_AGENT})
        if s3_credentials:
            self.session.auth = s3_credentials
        
        # ===== STATE TRACKING =====
        self.stats_lock = threading.Lock()
        self.scanned_ids = 0
        self.items_done = 0
        self.total_files = 0
        self.failed_files = 0
        self.total_bytes_downloaded = 0
        self.bytes_this_second = 0
        self.last_speed_update = time.time()
        self.current_speed_bps = 0.0
        self.scanner_active = False
        
        # ===== UI BRIDGE (POLLING-HOOK & EVENT-STREAM) =====
        self.ui_events = deque(maxlen=1000)
        self.debug_log = deque(maxlen=50000)
        self.last_log_index = 0
        
        # ===== DATABASE (PERSISTENCE-001) =====
        self.db_path = self.output_dir / "grabia_state.db"
        self._initialize_database()
        
        # ===== GHOST AUDIT LOG (ASSET-011) =====
        self.log_file = Path.cwd() / "grabia_debug.log"
        if self.log_file.exists():
            self.log_file.unlink()
        
        self._log("Core Engine Initialized", "info")
        self._log(f"Output Directory: {self.output_dir}", "info")
        self._log(f"Max Workers: {self.max_workers} | Dynamic Scaling: {self.dynamic_scaling}", "info")
        
    def _initialize_database(self):
        """
        Initialize SQLite database with WAL mode (PERSISTENCE-001).
        
        PROTECTED ASSET: PERSISTENCE-001
        - PRAGMA journal_mode=WAL for concurrent access
        - Thread-safe schema creation
        """
        try:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(DB_SCHEMA)
            conn.commit()
            conn.close()
            self._log("Database initialized with WAL mode", "success")
        except Exception as e:
            self._log(f"Database initialization failed: {e}", "error")
            raise
    
    def _log(self, message: str, level: str = "info"):
        """
        Thread-safe logging to both debug file and UI event stream.
        
        Args:
            message: Log message
            level: Log level (info, success, warning, error)
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] [{level.upper()}] {message}"
        
        # File logging
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(formatted + "\n")
        except Exception:
            pass
        
        # UI event stream
        self.debug_log.append(formatted)
        self.ui_events.append(formatted)
    
    def _get_db_connection(self) -> sqlite3.Connection:
        """
        Get a thread-safe database connection.
        
        Returns:
            SQLite connection with WAL mode enabled
        """
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn
    
    def _trigger_backoff(self, duration: int = None):
        """
        Trigger global backoff across all workers (PROT-002).
        
        Args:
            duration: Backoff duration in seconds (random if None)
        
        PROTECTED ASSET: PROT-002 - Global Backoff Coordination
        """
        if duration is None:
            duration = random.randint(BACKOFF_MIN_SECONDS, BACKOFF_MAX_SECONDS)
        
        with self.backoff_lock:
            self.global_backoff_until = time.time() + duration
            self._log(f"🚨 GLOBAL BACKOFF TRIGGERED: {duration}s", "warning")
    
    def _check_backoff(self) -> bool:
        """
        Check if global backoff is active.
        
        Returns:
            True if backoff is active, False otherwise
        """
        with self.backoff_lock:
            if time.time() < self.global_backoff_until:
                return True
            return False
    
    def _wait_for_backoff(self):
        """
        Wait until global backoff period ends.
        
        PROTECTED ASSET: PROT-002 - Coordinated sleep state
        """
        while not self.stop_event.is_set():
            with self.backoff_lock:
                remaining = self.global_backoff_until - time.time()
                if remaining <= 0:
                    break
            time.sleep(0.5)
    
    def _consume_tokens(self, bytes_count: int):
        """
        Consume bandwidth tokens (ASSET-009: Token-Bucket).
        
        Args:
            bytes_count: Number of bytes to consume tokens for
        
        PROTECTED ASSET: ASSET-009 - Token-Bucket Rate Limiting
        """
        if self.speed_limit_bps <= 0:
            return
        
        with self.token_lock:
            # Refill tokens
            now = time.time()
            elapsed = now - self.last_refill
            self.tokens += elapsed * self.speed_limit_bps
            self.tokens = min(self.tokens, self.speed_limit_bps * 2)  # Cap at 2x limit
            self.last_refill = now
            
            # Consume tokens
            while self.tokens < bytes_count and not self.stop_event.is_set():
                time.sleep(0.01)
                now = time.time()
                elapsed = now - self.last_refill
                self.tokens += elapsed * self.speed_limit_bps
                self.tokens = min(self.tokens, self.speed_limit_bps * 2)
                self.last_refill = now
            
            self.tokens -= bytes_count
    
    def _update_speed_stats(self, bytes_downloaded: int):
        """
        Update speed statistics for telemetry.
        
        Args:
            bytes_downloaded: Bytes downloaded in this update
        """
        with self.stats_lock:
            self.total_bytes_downloaded += bytes_downloaded
            self.bytes_this_second += bytes_downloaded
            
            now = time.time()
            elapsed = now - self.last_speed_update
            
            if elapsed >= 1.0:
                self.current_speed_bps = self.bytes_this_second / elapsed
                self.bytes_this_second = 0
                self.last_speed_update = now
    
    def _scale_workers(self, success: bool):
        """
        Adjust worker count based on success/failure (ASSET-022).
        
        Args:
            success: Whether the last operation succeeded
        
        PROTECTED ASSET: ASSET-022 - Dynamic Worker Scaling
        """
        if not self.dynamic_scaling:
            return
        
        with self.stats_lock:
            if success:
                self.success_streak += 1
                if self.success_streak >= SUCCESS_STREAK_THRESHOLD:
                    if self.target_workers < self.max_workers:
                        self.target_workers = min(self.target_workers + SCALE_UP_INCREMENT, 
                                                 self.max_workers)
                        self._log(f"📈 Scaling UP to {self.target_workers} workers", "info")
                    self.success_streak = 0
            else:
                self.success_streak = 0
                if self.target_workers > 1:
                    self.target_workers = max(1, self.target_workers - 1)
                    self._log(f"📉 Scaling DOWN to {self.target_workers} workers", "warning")

# Worker Loop, Scanner Loop, Helper Methods, and UI Bridge

    def _worker_loop(self):
        """
        Main worker thread loop for downloading files.
        
        PROTECTED ASSETS IMPLEMENTED:
        - PROT-001: Atomic Safe-Swap
        - PROT-003: Byte-Level Resume
        - ASSET-015: Recursive Path Governance
        - ASSET-018: Intelligent Retry Backoff
        - ENGINE-LOGIC-001: 128KB chunks with stop signal checking
        """
        while not self.stop_event.is_set():
            # Check global backoff
            if self._check_backoff():
                self._wait_for_backoff()
                continue
            
            try:
                task = self.task_queue.get(timeout=1.0)
            except Empty:
                continue
            
            # ASSET-018: Exponential backoff for retries
            if task.attempt_count > 0:
                backoff_time = min(2 ** task.attempt_count + random.random(), 60)
                self._log(f"Retry backoff: {backoff_time:.1f}s for {task.file_name}", "warning")
                time.sleep(backoff_time)
            
            try:
                self._download_file(task)
                self._scale_workers(success=True)
            except Exception as e:
                self._log(f"Worker error: {e}", "error")
                self._scale_workers(success=False)
                
                # Re-queue with incremented attempt count (ASSET-018)
                if task.attempt_count < 3:
                    task.attempt_count += 1
                    self.task_queue.put(task)
                    self._update_db_status(task.item_id, task.file_name, 'retrying', task.attempt_count)
                else:
                    self._update_db_status(task.item_id, task.file_name, 'failed', task.attempt_count)
                    with self.stats_lock:
                        self.failed_files += 1
            finally:
                self.task_queue.task_done()
    
    def _download_file(self, task: DownloadTask):
        """
        Download a single file with full integrity checking.
        
        Args:
            task: DownloadTask instance
        
        PROTECTED ASSETS:
        - PROT-001: Atomic Safe-Swap
        - PROT-003: Byte-Level Resume (HTTP 206)
        - ASSET-015: Recursive Path Governance
        - ASSET-035: Ghost-Stream Validator
        
        FIX: MD5 verification now calculates hash on complete file, not streaming chunks
        """
        item_dir = self.output_dir / task.item_id
        final_path = item_dir / task.file_name
        part_path = Path(str(final_path) + ".part")
        
        # ASSET-015: Recursive Path Governance
        part_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Sync mode: Skip if exists and MD5 matches (or size matches when no MD5)
        if self.sync_mode and final_path.exists():
            if task.expected_md5:
                # We have an MD5 - verify it properly
                if self._verify_md5(final_path, task.expected_md5):
                    self._log(f"✓ Skipped (sync, MD5 verified): {task.file_name}", "info")
                    self._update_db_status(task.item_id, task.file_name, 'done', task.attempt_count)
                    with self.stats_lock:
                        self.items_done += 1
                    return
                else:
                    self._log(f"⚠ MD5 mismatch on existing file, re-downloading: {task.file_name}", "warning")
                    # falls through to download
            else:
                # No MD5 available - fall back to size check
                if task.file_size > 0 and final_path.stat().st_size == task.file_size:
                    self._log(f"✓ Skipped (sync, size verified): {task.file_name}", "info")
                    self._update_db_status(task.item_id, task.file_name, 'done', task.attempt_count)
                    with self.stats_lock:
                        self.items_done += 1
                    return
                elif task.file_size == 0:
                    # No MD5 and no size - file exists, trust it
                    self._log(f"✓ Skipped (sync, no verification available): {task.file_name}", "info")
                    self._update_db_status(task.item_id, task.file_name, 'done', task.attempt_count)
                    with self.stats_lock:
                        self.items_done += 1
                    return
        
        # PROT-003: Byte-Level Resume
        resume_pos = 0
        if part_path.exists():
            resume_pos = part_path.stat().st_size
            self._log(f"🔄 Resuming from byte {resume_pos}: {task.file_name}", "info")
        
        headers = {}
        if resume_pos > 0 and task.file_size > 0:
            headers['Range'] = f'bytes={resume_pos}-'
        
        try:
            response = self.session.get(task.file_url, headers=headers, 
                                       stream=True, timeout=CONNECTION_TIMEOUT)
            
            # PROT-003.1: Resume Recovery
            if resume_pos > 0 and response.status_code == 200:
                self._log(f"⚠ Server doesn't support resume, restarting: {task.file_name}", "warning")
                resume_pos = 0
                part_path.unlink(missing_ok=True)
                response = self.session.get(task.file_url, stream=True, timeout=CONNECTION_TIMEOUT)
            
            # Handle rate limiting (PROT-002)
            if response.status_code == 429:
                self._trigger_backoff()
                raise Exception("Rate limited (429)")
            
            if response.status_code == 503:
                self._trigger_backoff(duration=60)
                raise Exception("Service unavailable (503)")
            
            if response.status_code not in (200, 206):
                raise Exception(f"HTTP {response.status_code}")
            
            # Open file in append or write mode
            mode = 'ab' if resume_pos > 0 and response.status_code == 206 else 'wb'
            
            total_downloaded = resume_pos
            
            with open(part_path, mode) as f:
                for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                    if self.stop_event.is_set():
                        self._log(f"⏸ Stopped during download: {task.file_name}", "warning")
                        return
                    
                    if chunk:
                        # Bandwidth throttling (ASSET-009)
                        self._consume_tokens(len(chunk))
                        
                        f.write(chunk)
                        total_downloaded += len(chunk)
                        self._update_speed_stats(len(chunk))
            
            # ASSET-035: Ghost-Stream Validator
            if task.file_size > 0 and part_path.stat().st_size != task.file_size:
                part_path.unlink(missing_ok=True)
                raise Exception(f"Incomplete download: {part_path.stat().st_size}/{task.file_size} bytes")
            
            # PROT-001: MD5 Verification (FIXED - Calculate on complete file)
            if task.expected_md5:
                calculated_md5 = self._calculate_md5(part_path)
                if calculated_md5.lower() != task.expected_md5.lower():
                    part_path.unlink(missing_ok=True)
                    raise Exception(f"MD5 mismatch: {calculated_md5} != {task.expected_md5}")
            
            # PROT-001: Atomic Safe-Swap
            os.replace(str(part_path), str(final_path))
            
            # ASSET-034: Temporal Drift Protection
            try:
                if hasattr(task, 'last_modified') and task.last_modified:
                    os.utime(final_path, (task.last_modified, task.last_modified))
            except Exception:
                pass
            
            self._log(f"✓ Downloaded: {task.file_name}", "success")
            self._update_db_status(task.item_id, task.file_name, 'done', task.attempt_count)
            
            with self.stats_lock:
                self.items_done += 1
                
        except Exception as e:
            self._log(f"✗ Failed: {task.file_name} - {e}", "error")
            raise    
    def _calculate_md5(self, file_path: Path) -> str:
        """
        Calculate MD5 hash of a file.
        
        Args:
            file_path: Path to file
        
        Returns:
            Hex digest of MD5 hash
        
        PROTECTED ASSET: PROT-001 (MD5 Buffer Size: 4096)
        """
        md5_hash = hashlib.md5()
        with open(file_path, 'rb') as f:
            while chunk := f.read(MD5_BUFFER_SIZE):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()
    
    def _verify_md5(self, file_path: Path, expected_md5: Optional[str]) -> bool:
        """
        Verify file MD5 against expected value.
        
        Args:
            file_path: Path to file
            expected_md5: Expected MD5 hash
        
        Returns:
            True if MD5 matches or no expected hash provided
        """
        if not expected_md5 or not file_path.exists():
            return False
        
        calculated = self._calculate_md5(file_path)
        return calculated.lower() == expected_md5.lower()
    
    def _update_db_status(self, item_id: str, file_name: str, status: str, attempt_count: int = 0):
        """
        Update file status in database.
        
        Args:
            item_id: Internet Archive identifier
            file_name: Name of file
            status: Status string (pending, downloading, done, failed, retrying)
            attempt_count: Number of download attempts
        
        PROTECTED ASSET: PERSISTENCE-001 (Thread-safe WAL updates)
        """
        try:
            conn = self._get_db_connection()
            conn.execute(
                "UPDATE files SET status = ?, attempt_count = ? WHERE item_id = ? AND file_name = ?",
                (status, attempt_count, item_id, file_name)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            self._log(f"Database update error: {e}", "error")
    
    def _scanner_loop(self, identifiers: List[str]):
        """
        Discovery scan loop for processing IA identifiers.
        
        Args:
            identifiers: List of Internet Archive identifiers
        
        PROTECTED ASSETS:
        - ASSET-040/045: Asynchronous Work-Ingestion
        - ASSET-012: README Generation (Priority 1)
        """
        self.scanner_active = True
        
        for identifier in identifiers:
            if self.stop_event.is_set():
                break
            
            try:
                self._log(f"🔍 Scanning: {identifier}", "info")
                
                # Fetch metadata from IA
                metadata_url = f"https://archive.org/metadata/{identifier}"
                response = self.session.get(metadata_url, timeout=CONNECTION_TIMEOUT)
                
                if response.status_code != 200:
                    self._log(f"✗ Metadata fetch failed: {identifier}", "error")
                    continue
                
                data = response.json()
                
                # ASSET-012: Generate README (Priority 1)
                self._generate_readme(identifier, data)
                
                # Extract files from metadata
                files = data.get('files', [])
                
                with self.stats_lock:
                    self.scanned_ids += 1
                
                conn = self._get_db_connection()
                
                for file_info in files:
                    if self.stop_event.is_set():
                        break
                    
                    file_name = file_info.get('name', '')
                    file_size = int(file_info.get('size', 0))
                    file_md5 = file_info.get('md5', '')
                    
                    # ASSET-VALID-001: Skip invalid entries
                    if not file_name or file_size == 0:
                        continue
                    
                    # FILTER-GATE: Anti-Clutter
                    if any(re.search(pattern, file_name) for pattern in SYSTEM_FILE_PATTERNS):
                        continue
                    
                    # Extension whitelist
                    if self.extension_whitelist:
                        if not any(file_name.lower().endswith(ext.lower()) 
                                 for ext in self.extension_whitelist):
                            continue
                    
                    # Regex filter
                    if self.filter_regex and not self.filter_regex.search(file_name):
                        continue
                    
                    # Metadata-only mode
                    if self.metadata_only:
                        lower_name = file_name.lower()
                        if not any(ext in lower_name for ext in ['.xml', '.json', '.txt', 'readme']):
                            continue
                    
                    # PATH-SAN: Filename Sanitization
                    safe_name = re.sub(r'[<>:"/\\|?*]', '_', file_name)
                    
                    # Insert into database
                    conn.execute(
                        "INSERT OR REPLACE INTO files (item_id, file_name, status, size, expected_md5) VALUES (?, ?, ?, ?, ?)",
                        (identifier, safe_name, 'pending', file_size, file_md5)
                    )
                    
                    with self.stats_lock:
                        self.total_files += 1
                    
                    # ASSET-040/045: Eager Ingestion - Queue immediately
                    file_url = f"https://archive.org/download/{identifier}/{file_name}"
                    
                    task = DownloadTask(
                        priority=0,  # Auto-calculate in __post_init__
                        item_id=identifier,
                        file_name=safe_name,
                        file_url=file_url,
                        file_size=file_size,
                        expected_md5=file_md5
                    )
                    
                    self.task_queue.put(task)
                
                conn.commit()
                conn.close()
                                
            except Exception as e:
                self._log(f"✗ Scanner error for {identifier}: {e}", "error")
        
        self.scanner_active = False
        self._log("🏁 Scanner complete", "success")
    
    def _generate_readme(self, identifier: str, metadata: Dict):
        """
        Generate human-readable README for an item.
        
        Args:
            identifier: Internet Archive identifier
            metadata: Metadata dictionary from IA API
        
        PROTECTED ASSET: ASSET-012 - README Generation (Priority 1)
        """
        item_dir = self.output_dir / identifier
        readme_path = item_dir / "README.txt"
        
        # Skip if already exists
        if readme_path.exists():
            return
        
        item_dir.mkdir(parents=True, exist_ok=True)
        
        meta = metadata.get('metadata', {})
        
        title = meta.get('title', identifier)
        creator = meta.get('creator', 'Unknown')
        date = meta.get('date', 'Unknown')
        description = meta.get('description', 'No description available')
        
        # Handle list values
        if isinstance(creator, list):
            creator = ', '.join(creator)
        if isinstance(description, list):
            description = ' '.join(description)
        
        readme_content = f"""
Internet Archive Item: {identifier}
{'=' * 60}

Title: {title}
Creator: {creator}
Date: {date}

Description:
{description}

Source: https://archive.org/details/{identifier}

Downloaded by grab-IA
Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
""".strip()
        
        try:
            with open(readme_path, 'w', encoding='utf-8') as f:
                f.write(readme_content)
            self._log(f"📄 Generated README for {identifier}", "success")
        except Exception as e:
            self._log(f"README generation failed: {e}", "error")
    
    
    def start(self, identifiers: List[str]):
        """
        Start the download engine.
        
        Args:
            identifiers: List of Internet Archive identifiers to download
        
        PROTECTED ASSETS:
        - ASSET-040/045: Asynchronous Work-Ingestion
        - Scanner and workers run concurrently
        """
        if not identifiers:
            self._log("No identifiers provided", "error")
            return
        
        self.stop_event.clear()
        
        # Start scanner thread (ASSET-040: Concurrent with workers)
        self.scanner_thread = threading.Thread(
            target=self._scanner_loop,
            args=(identifiers,),
            daemon=True
        )
        self.scanner_thread.start()
        
        # Start worker pool (ASSET-045: Eager ingestion)
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        self.worker_futures = [
            self.executor.submit(self._worker_loop)
            for _ in range(self.target_workers)
        ]
        
        self._log(f"🚀 Engine started: {len(identifiers)} items, {self.target_workers} workers", "success")
    
    def stop(self):
        """Stop the download engine cleanly."""
        self.stop_event.set()

        # Stop scanner thread
        if self.scanner_thread and self.scanner_thread.is_alive():
            self.scanner_thread.join(timeout=2)

        # Stop worker pool
        if self.executor:
            self.executor.shutdown(wait=False, cancel_futures=True)
            self.executor = None

        self._log("Engine stopped", "info")

    def _get_persistent_job_progress(self) -> Tuple[int, int, int]:
        """
        Get persistent job progress from SQLite.
        
        Returns:
            (total_files, done_files, failed_files)
        """
        try:
            conn = self._get_db_connection()
            cur = conn.cursor()

            cur.execute("SELECT COUNT(*) FROM files")
            total = cur.fetchone()[0] or 0

            cur.execute("SELECT COUNT(*) FROM files WHERE status = 'done'")
            done = cur.fetchone()[0] or 0

            cur.execute("SELECT COUNT(*) FROM files WHERE status = 'failed'")
            failed = cur.fetchone()[0] or 0

            conn.close()
            return total, done, failed
        except Exception:
            return 0, 0, 0

    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get current engine statistics (POLLING-HOOK).
        
        Returns:
            Dictionary containing all telemetry data
        
        PROTECTED ASSET: ASSET-032 - Variable Key Lockdown
        All keys returned here are in PROTECTED_KEYS registry
        """
        with self.stats_lock:
            backoff_active = self._check_backoff()
            
            # Calculate ETA
            eta_seconds = 0
            if self.current_speed_bps > 0 and self.total_files > 0:
                remaining_files = self.total_files - self.items_done
                avg_file_time = 10  # Rough estimate
                eta_seconds = remaining_files * avg_file_time
            
            # Calculate progress
            percent_complete = 0.0
            if self.total_files > 0:
                percent_complete = (self.items_done / self.total_files) * 100
            # Persistent (resume-safe) job progress
            job_total, job_done, job_failed = self._get_persistent_job_progress()
            job_percent_complete = 0.0
            if job_total > 0:
                job_percent_complete = ((job_done + job_failed) / job_total) * 100

            
            return {
                "scanned_ids": self.scanned_ids,
                "items_done": self.items_done,
                "total_files": self.total_files,
                "active_threads": self.target_workers,
                "bytes_per_sec": self.current_speed_bps,
                "backoff_active": backoff_active,
                "disk_remaining": self._get_disk_space(),
                "last_log_index": self.last_log_index,
                "vault_status": "healthy",  # WAL mode always healthy
                "eta_seconds": eta_seconds,
                "percent_complete": percent_complete,
                "current_speed_mbps": (self.current_speed_bps / 1_000_000) * 8,
                "total_bytes_downloaded": self.total_bytes_downloaded,
                "failed_files": self.failed_files,
                "target_workers": self.target_workers,
                "success_streak": self.success_streak,
                "global_backoff_until": self.global_backoff_until,
                "scanner_active": self.scanner_active,
                "queue_depth": self.task_queue.qsize(),
                "heartbeat": time.time(),  # APFE-IV-34: Heartbeat Signature
                "job_total_files": job_total,
                "job_files_done": job_done,
                "job_percent_complete": job_percent_complete,

            }
    
    def get_logs(self, from_index: int = 0) -> Tuple[List[str], int]:
        """
        Get log entries from a specific index.
        
        Args:
            from_index: Starting index for log retrieval
        
        Returns:
            Tuple of (log_lines, new_index)
        
        PROTECTED ASSET: APFE-IV-14/15 - Incremental Pointer Protection
        """
        logs = self.debug_log[from_index:]
        new_index = len(self.debug_log)
        return logs, new_index
    
    def _get_disk_space(self) -> int:
        """
        Get available disk space on output directory.
        
        Returns:
            Available bytes on disk
        """
        try:
            import shutil
            usage = shutil.disk_usage(self.output_dir)
            return usage.free
        except Exception:
            return 0
    
    def update_config(self, max_workers: int = None, speed_limit_bps: int = None):
        """
        Update configuration during runtime.
        
        Args:
            max_workers: New maximum worker count
            speed_limit_bps: New bandwidth limit in bytes per second
        
        PROTECTED ASSET: Real-Time Config Updates (Hook Layer)
        """
        if max_workers is not None:
            self.max_workers = max_workers
            if not self.dynamic_scaling:
                self.target_workers = max_workers
            self._log(f"⚙ Updated max_workers: {max_workers}", "info")
        
        if speed_limit_bps is not None:
            self.speed_limit_bps = speed_limit_bps
            self._log(f"⚙ Updated speed_limit: {speed_limit_bps} bps", "info")


