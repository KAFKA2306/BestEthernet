import subprocess
import tkinter as tk
from tkinter import ttk

def get_all_interfaces():
    cmd = ["powershell", "-Command", "Get-NetAdapter | Select-Object -ExpandProperty Name"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    interfaces = result.stdout.strip().split('\n')
    print(f"すべてのインターフェース: {interfaces}")  # デバッグ出力
    return interfaces

def enable_all_interfaces(interfaces):
    for interface in interfaces:
        cmd = ["powershell", "-Command", f"Enable-NetAdapter -Name \"{interface}\" -Confirm:$false"]
        subprocess.run(cmd, capture_output=True, text=True)
        print(f"{interface} を有効にしました。")

def get_mobile_hotspot_capable_interfaces():
    cmd = ["powershell", "-Command", "Get-NetAdapter | Where-Object {$_.HotspotCapable -eq $true} | Select-Object -ExpandProperty Name"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    hotspot_interfaces = result.stdout.strip().split('\n')
    print(f"ホットスポット可能なインターフェース: {hotspot_interfaces}")  # デバッグ出力
    return hotspot_interfaces

def start_mobile_hotspot(interface):
    cmd = ["powershell", "-Command", f"Set-NetAdapter -Name \"{interface}\" -HotspotEnabled $true"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"{interface} のモバイルホットスポットを開始しました。")
    else:
        print(f"{interface} のモバイルホットスポット開始に失敗しました。エラー: {result.stderr}")

class HotspotSelector:
    def __init__(self, root):
        self.root = root
        self.root.title("モバイルホットスポットセレクター")
        self.selected_interface = tk.StringVar()
        self.setup_ui()

    def setup_ui(self):
        frame = ttk.Frame(self.root, padding="10")
        frame.grid(column=0, row=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        ttk.Label(frame, text="インターフェースを選択してください:").grid(column=0, row=0, sticky=tk.W, pady=5)

        self.interface_listbox = tk.Listbox(frame, height=10, width=50)
        self.interface_listbox.grid(column=0, row=1, pady=5)
        self.interface_listbox.bind('<<ListboxSelect>>', self.on_select)

        self.start_button = ttk.Button(frame, text="モバイルホットスポットを開始", command=self.start_hotspot, state=tk.DISABLED)
        self.start_button.grid(column=0, row=2, pady=5)

        self.status_label = ttk.Label(frame, text="")
        self.status_label.grid(column=0, row=3, pady=5)

        self.load_interfaces()

    def load_interfaces(self):
        all_interfaces = get_all_interfaces()
        enable_all_interfaces(all_interfaces)
        hotspot_interfaces = get_mobile_hotspot_capable_interfaces()
        if not hotspot_interfaces:
            self.status_label['text'] = "ホットスポット可能なインターフェースが見つかりませんでした。"
            return
        for interface in hotspot_interfaces:
            self.interface_listbox.insert(tk.END, interface)
        print(f"リストボックスに追加されたインターフェース: {self.interface_listbox.get(0, tk.END)}")  # デバッグ出力

    def on_select(self, event):
        if self.interface_listbox.curselection():
            self.selected_interface.set(self.interface_listbox.get(self.interface_listbox.curselection()))
            self.start_button['state'] = tk.NORMAL
        else:
            self.start_button['state'] = tk.DISABLED

    def start_hotspot(self):
        selected = self.selected_interface.get()
        if selected:
            start_mobile_hotspot(selected)
            self.status_label['text'] = f"{selected} のモバイルホットスポットを開始しました。"
        else:
            self.status_label['text'] = "インターフェースを選択してください。"

if __name__ == "__main__":
    root = tk.Tk()
    app = HotspotSelector(root)
    root.mainloop()