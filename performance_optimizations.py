"""
Performance optimizations for Allocator AI based on hardware
"""

import asyncio
import concurrent.futures
from typing import List
import time

class PerformanceOptimizer:
    """Hardware-aware performance optimizations"""
    
    def __init__(self, cpu_cores: int = 4, ram_gb: int = 8):
        self.cpu_cores = cpu_cores
        self.ram_gb = ram_gb
        self.optimal_batch_size = self._calculate_batch_size()
        self.max_workers = self._calculate_max_workers()
    
    def _calculate_batch_size(self) -> int:
        """Calculate optimal batch size based on available RAM"""
        if self.ram_gb >= 16:
            return 500  # Large batches for high-memory systems
        elif self.ram_gb >= 8:
            return 200  # Medium batches
        else:
            return 50   # Small batches for low-memory systems
    
    def _calculate_max_workers(self) -> int:
        """Calculate optimal worker threads based on CPU cores"""
        if self.cpu_cores >= 8:
            return 6  # Leave 2 cores for other processes
        elif self.cpu_cores >= 4:
            return 3  # Leave 1 core free
        else:
            return 2  # Conservative for dual-core
    
    async def optimized_block_scan(self, w3, start_block: int, end_block: int):
        """Optimized parallel block scanning"""
        
        # Split blocks into batches
        block_ranges = []
        total_blocks = end_block - start_block + 1
        
        for i in range(0, total_blocks, self.optimal_batch_size):
            batch_start = start_block + i
            batch_end = min(start_block + i + self.optimal_batch_size - 1, end_block)
            block_ranges.append((batch_start, batch_end))
        
        # Process batches in parallel
        candidate_stats = {}
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_range = {
                executor.submit(self._scan_block_range, w3, start, end): (start, end)
                for start, end in block_ranges
            }
            
            for future in concurrent.futures.as_completed(future_to_range):
                try:
                    batch_results = future.result()
                    # Merge results
                    for addr, stats in batch_results.items():
                        if addr not in candidate_stats:
                            candidate_stats[addr] = {"trades": 0, "profit": 0}
                        candidate_stats[addr]["trades"] += stats["trades"]
                        candidate_stats[addr]["profit"] += stats["profit"]
                except Exception as e:
                    print(f"Batch failed: {e}")
        
        return candidate_stats
    
    def _scan_block_range(self, w3, start_block: int, end_block: int):
        """Scan a range of blocks - optimized for single thread"""
        candidate_stats = {}
        
        # Batch RPC calls for better network efficiency
        try:
            # Use batch requests if supported by your RPC
            blocks = []
            for block_num in range(start_block, end_block + 1):
                try:
                    block = w3.eth.get_block(block_num, full_transactions=True)
                    blocks.append(block)
                except:
                    continue
            
            # Process all blocks in memory (CPU optimization)
            for block in blocks:
                for tx in block.transactions:
                    if tx.to and tx.to.lower() in [
                        "0x7a250d5630b4cf539739df2c5dacb4c659f2488d",
                        "0xe592427a0aece92de3edee1f18e0157c05861564"
                    ]:
                        actor = tx["from"].lower()
                        if actor not in candidate_stats:
                            candidate_stats[actor] = {"trades": 0, "profit": 0}
                        candidate_stats[actor]["trades"] += 1
                        candidate_stats[actor]["profit"] += tx.value / (10**18)
                        
        except Exception as e:
            print(f"Error scanning blocks {start_block}-{end_block}: {e}")
        
        return candidate_stats

# Hardware-specific configurations
HARDWARE_CONFIGS = {
    "budget_vps": {
        "cpu_cores": 2,
        "ram_gb": 4,
        "discovery_refresh": 600,  # 10 minutes
        "max_concurrent_modes": 2
    },
    "standard_vps": {
        "cpu_cores": 4,
        "ram_gb": 8,
        "discovery_refresh": 300,  # 5 minutes
        "max_concurrent_modes": 3
    },
    "high_performance": {
        "cpu_cores": 8,
        "ram_gb": 16,
        "discovery_refresh": 180,  # 3 minutes
        "max_concurrent_modes": 5
    }
}

def get_hardware_config(config_name: str = "standard_vps"):
    """Get optimized settings for your hardware"""
    return HARDWARE_CONFIGS.get(config_name, HARDWARE_CONFIGS["standard_vps"])
