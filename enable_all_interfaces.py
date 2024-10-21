import subprocess

def get_ethernet_interfaces():
    # すべてのネットワークアダプタを取得
    result = subprocess.run(["powershell", "-Command", "Get-NetAdapter | Select-Object -ExpandProperty Name"], capture_output=True, text=True)
    interfaces = result.stdout.strip().split('\n')
    return interfaces

def enable_all_ethernet_interfaces(interfaces):
    for interface in interfaces:
        # すべてのインターフェースを有効にする
        subprocess.run(["powershell", "-Command", f"Enable-NetAdapter -Name \"{interface}\" -Confirm:$false"], capture_output=True, text=True)
        print(f"{interface}を有効にしました。")

def main():
    interfaces = get_ethernet_interfaces()
    print("全てのイーサネットインターフェース:", interfaces)
    enable_all_ethernet_interfaces(interfaces)

if __name__ == "__main__":
    main()