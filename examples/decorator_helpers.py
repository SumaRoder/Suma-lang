from __future__ import annotations


def plus(delta: int):
    def decorate(func):
        def wrapper(*args):
            return func(*args) + delta

        return wrapper

    return decorate


def trace(label: str):
    def decorate(func):
        def wrapper(*args):
            print(f"[trace:{label}] before")
            result = func(*args)
            print(f"[trace:{label}] after = {result}")
            return result

        return wrapper

    return decorate


def identity(func):
    return func
