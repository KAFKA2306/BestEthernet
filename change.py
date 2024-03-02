import subprocess
import tkinter as tk
from tkinter import ttk

class EthernetInterfaceSwitcher:
    def __init__(self, root):
        self.root = root
        self.interfaces = self.get_ethernet_interfaces()
        self.setup_ui()

    @staticmethod
    def get_ethernet_interfaces():
        cmd = ["powershell", "-Command", "Get-NetAdapter | Where-Object {$_.Status -eq 'Up' -or $_.Status -eq 'Disconnected'} | Select-Object -ExpandProperty Name"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        interfaces = result.stdout.strip().split('\n')
        return interfaces

    @staticmethod
    def switch_ethernet_interface(interface_name, enable=True):
        # まず、すべてのインターフェースを取得
        cmd_get_all = ["powershell", "-Command", "Get-NetAdapter | Select-Object -ExpandProperty Name"]
        result_all = subprocess.run(cmd_get_all, capture_output=True, text=True)
        all_interfaces = result_all.stdout.strip().split('\n')

        # 指定されたインターフェース以外を無効にする
        for intf in all_interfaces:
            if intf != interface_name:
                subprocess.run(["powershell", "-Command", f"Disable-NetAdapter -Name \"{intf}\" -Confirm:$false"], capture_output=True, text=True)

        # 指定されたインターフェースを有効にする
        if enable:
            action = "Enable-NetAdapter"
            subprocess.run(["powershell", "-Command", f"{action} -Name \"{interface_name}\" -Confirm:$false"], capture_output=True, text=True)
            state = "有効"
        else:
            state = "無効"  # この行は実際には必要ありませんが、将来の変更のために残しています。

        print(f"{interface_name}を{state}にしました。")

    def setup_ui(self):
        self.root.title("イーサネットインターフェース切り替えツール")
        mainframe = ttk.Frame(self.root, padding="3 3 12 12")
        mainframe.grid(column=0, row=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.selected_interface = tk.StringVar()
        interface_combobox = ttk.Combobox(mainframe, textvariable=self.selected_interface, values=self.interfaces)
        interface_combobox.grid(column=2, row=1, sticky=(tk.W, tk.E))
        ttk.Label(mainframe, text="インターフェース選択:").grid(column=1, row=1, sticky=tk.W)

        ttk.Button(mainframe, text="切り替え", command=self.switch_interface).grid(column=2, row=2, sticky=tk.W)
        interface_combobox.bind('<<ComboboxSelected>>', self.switch_interface)

        for child in mainframe.winfo_children():
            child.grid_configure(padx=5, pady=5)

        interface_combobox.focus()

    def switch_interface(self, *args):
        interface_name = self.selected_interface.get()
        EthernetInterfaceSwitcher.switch_ethernet_interface(interface_name, enable=True)

if __name__ == "__main__":
    root = tk.Tk()
    app = EthernetInterfaceSwitcher(root)
    root.mainloop()
