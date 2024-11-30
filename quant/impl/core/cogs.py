import importlib
import os
import time
import inspect
import sys
from quant.impl.core.commands import SlashCommand
from typing import List


class Cog:
    def __init__(self, client, name: str, description: str = "No description"):
        self.client = client
        self.name = name
        self.description = description
        self._register_commands()


    def _register_commands(self):
        methods = inspect.getmembers(self, predicate=inspect.ismethod)
        print("Found methods in Cog:", [method[0]
              for method in methods])  # dbg

        registered_commands = set()

        commands = []
        for _, method in methods:
            if hasattr(method, "__is_command__"):
                command_name = getattr(method, "__command_name__")
                command_desc = getattr(
                    method, "__command_description__", "No description")
                commands.append((command_name, command_desc, method))

        for command_name, command_desc, method in commands:
            if command_name in registered_commands:
                continue

            print(f"Attempting to register command: {command_name}")  # dbg

            # ебал
            command = SlashCommand(name=f"{command_name}_{id(method)}", description=command_desc)
            command.set_callback(method)

            try:
                self.client.add_slash_command(command)
                time.sleep(2)
                registered_commands.add(command_name)
                print(f"Successfully registered command: {command_name}")
            except Exception as e:
                print(f"Failed to register command: {command_name}: {e}")



    def _get_retry_time(self, error) -> int:
        retry_after = 30
        if hasattr(error, 'retry_after'):
            retry_after = error.retry_after
        return retry_after


def command(name: str = None, description: str = None):
    def decorator(func):
        func.__is_command__ = True
        func.__command_name__ = name or func.__name__
        func.__command_description__ = description or "No description"
        return func
    return decorator


class CogLoader:
    def __init__(self, cogs_dir: str):
        self.cogs_dir = cogs_dir
        root_dir = os.path.abspath(os.path.join(cogs_dir, "../.."))
        if root_dir not in sys.path:
            sys.path.insert(0, root_dir)

    def load_cogs(self) -> List[str]:
        loaded_cogs = []
        for root, _, files in os.walk(self.cogs_dir):
            for file in files:
                if file.endswith(".py") and not file.startswith("__"):
                    file_path = os.path.join(root, file)
                    module_name = os.path.splitext(
                        os.path.basename(file_path))[0]

                    try:
                        spec = importlib.util.spec_from_file_location(
                            module_name, file_path)
                        if spec and spec.loader:
                            module = importlib.util.module_from_spec(spec)
                            sys.modules[module_name] = module
                            spec.loader.exec_module(module)
                            loaded_cogs.append(module_name)
                            print(f"Loaded: {module_name}")
                        else:
                            print(f"Failed to load spec for {module_name}")

                    except Exception as e:
                        print(
                            f"Failed to load {module_name}: {type(e).__name__}: {e}")

        return loaded_cogs
