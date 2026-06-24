import threading

class ThreadSafeDict(dict):
    def __init__(self, *args, **kwargs):
        self.lock = threading.RLock()
        super().__init__(*args, **kwargs)

    def __getitem__(self, key):
        with self.lock: return super().__getitem__(key)
    def __setitem__(self, key, value):
        with self.lock: super().__setitem__(key, value)
    def __delitem__(self, key):
        with self.lock: super().__delitem__(key)
    def get(self, key, default=None):
        with self.lock: return super().get(key, default)
    def update(self, *args, **kwargs):
        with self.lock: super().update(*args, **kwargs)
    def clear(self):
        with self.lock: super().clear()
    def pop(self, key, default=None):
        with self.lock: return super().pop(key, default)
    def copy(self):
        with self.lock: return super().copy()

user_state = ThreadSafeDict()
state_lock = threading.RLock()

pinned_messages = ThreadSafeDict()
pinned_lock = threading.RLock()

admin_cache = None
