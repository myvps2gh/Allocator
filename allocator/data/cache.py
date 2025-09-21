"""
Caching system for Allocator AI
"""

import time
import threading
from typing import Any, Optional, Dict
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


class TTLCache:
    """Time-to-live cache for expensive operations"""
    
    def __init__(self, ttl_seconds: int = 300):
        self.cache = {}
        self.ttl = ttl_seconds
        self.lock = threading.Lock()
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired"""
        with self.lock:
            if key in self.cache:
                value, timestamp = self.cache[key]
                if time.time() - timestamp < self.ttl:
                    return value
                else:
                    del self.cache[key]
            return None
    
    def set(self, key: str, value: Any) -> None:
        """Set value in cache with current timestamp"""
        with self.lock:
            self.cache[key] = (value, time.time())
    
    def clear(self) -> None:
        """Clear all cached values"""
        with self.lock:
            self.cache.clear()
    
    def size(self) -> int:
        """Get current cache size"""
        with self.lock:
            return len(self.cache)
    
    def cleanup_expired(self) -> int:
        """Remove expired entries and return count of removed items"""
        with self.lock:
            now = time.time()
            expired_keys = [
                key for key, (value, timestamp) in self.cache.items()
                if now - timestamp >= self.ttl
            ]
            for key in expired_keys:
                del self.cache[key]
            return len(expired_keys)


class CacheManager:
    """Centralized cache management for different data types"""
    
    def __init__(self):
        self.caches = {
            'token': TTLCache(ttl_seconds=3600),      # 1 hour for token data
            'price': TTLCache(ttl_seconds=60),        # 1 minute for prices
            'whale': TTLCache(ttl_seconds=1800),      # 30 minutes for whale data
            'moralis': TTLCache(ttl_seconds=3600),    # 1 hour for Moralis data
            'web3': TTLCache(ttl_seconds=300)         # 5 minutes for Web3 calls
        }
    
    def get(self, cache_type: str, key: str) -> Optional[Any]:
        """Get value from specific cache"""
        if cache_type in self.caches:
            return self.caches[cache_type].get(key)
        return None
    
    def set(self, cache_type: str, key: str, value: Any) -> None:
        """Set value in specific cache"""
        if cache_type in self.caches:
            self.caches[cache_type].set(key, value)
        else:
            logger.warning(f"Unknown cache type: {cache_type}")
    
    def clear(self, cache_type: Optional[str] = None) -> None:
        """Clear cache(s)"""
        if cache_type:
            if cache_type in self.caches:
                self.caches[cache_type].clear()
        else:
            for cache in self.caches.values():
                cache.clear()
    
    def cleanup_all(self) -> Dict[str, int]:
        """Cleanup all expired entries and return counts"""
        results = {}
        for name, cache in self.caches.items():
            results[name] = cache.cleanup_expired()
        return results
    
    def get_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get cache statistics"""
        stats = {}
        for name, cache in self.caches.items():
            stats[name] = {
                'size': cache.size(),
                'ttl': cache.ttl
            }
        return stats


class RateLimiter:
    """Rate limiter to prevent API abuse and manage request frequency"""
    
    def __init__(self, max_calls: int, time_window: int):
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = defaultdict(list)
        self.lock = threading.Lock()
    
    def can_make_call(self, key: str) -> bool:
        """Check if a call can be made for the given key"""
        with self.lock:
            now = time.time()
            # Remove old calls outside the time window
            self.calls[key] = [call_time for call_time in self.calls[key] 
                              if now - call_time < self.time_window]
            
            return len(self.calls[key]) < self.max_calls
    
    def record_call(self, key: str) -> None:
        """Record a call for the given key"""
        with self.lock:
            self.calls[key].append(time.time())
    
    def get_remaining_calls(self, key: str) -> int:
        """Get remaining calls for the given key"""
        with self.lock:
            now = time.time()
            self.calls[key] = [call_time for call_time in self.calls[key] 
                              if now - call_time < self.time_window]
            return max(0, self.max_calls - len(self.calls[key]))
    
    def get_stats(self, key: str) -> Dict[str, Any]:
        """Get rate limiter stats for a key"""
        with self.lock:
            now = time.time()
            self.calls[key] = [call_time for call_time in self.calls[key] 
                              if now - call_time < self.time_window]
            return {
                'calls_made': len(self.calls[key]),
                'remaining': max(0, self.max_calls - len(self.calls[key])),
                'reset_time': self.calls[key][0] + self.time_window if self.calls[key] else now
            }
