import subprocess
import tkinter as tk
from tkinter import ttk
import os

def run_powershell_command(command):
    result = subprocess.run(["powershell", "-Command", command], capture_output=True, text=True)
    print(f"Command: {command}")
    print(f"Output: {result.stdout}")
    print(f"Error: {result.stderr}")
    return result.stdout.strip().split('\n')

def get_wifi_interfaces():
    return run_powershell_command("Get-NetAdapter | Where-Object {$_.InterfaceDescription -match 'Wi-Fi|Wireless|WLAN'} | Select-Object -ExpandProperty Name")

def start_mobile_hotspot():
    # Windows 10のモバイルホットスポット機能を直接使用
    commands = [
        "$networks = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::AvailableTetheringOperators",
        "$networks[0].StartTetheringAsync()",
    ]
    command = "; ".join(commands)
    return run_powershell_command(command)

def open_hotspot_settings():
    os.system('start ms-settings:network-mobilehotspot')

class HotspotActivator:
    def __init__(self, root):
        self.root = root
        self.root.title("Windows 10 モバイルホットスポットアクティベーター")
        self.setup_ui()

    def setup_ui(self):
        frame = ttk.Frame(self.root, padding="10")
        frame.grid(column=0, row=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        ttk.Button(frame, text="モバイルホットスポットを開始", command=self.activate_hotspot).grid(column=0, row=0, pady=5)
        ttk.Button(frame, text="ホットスポット設定を開く", command=open_hotspot_settings).grid(column=0, row=1, pady=5)

        self.status_label = ttk.Label(frame, text="")
        self.status_label.grid(column=0, row=2, pady=5)

    def activate_hotspot(self):
        result = start_mobile_hotspot()
        if "エラー" not in " ".join(result).lower():
            self.status_label['text'] = "モバイルホットスポットを開始しました。"
        else:
            self.status_label['text'] = "モバイルホットスポットの開始に失敗しました。設定を確認してください。"

if __name__ == "__main__":
    root = tk.Tk()
    app = HotspotActivator(root)
    root.mainloop()