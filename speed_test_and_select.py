import subprocess
import speedtest
import datetime
import csv
import time

def get_ethernet_interfaces():
    result = subprocess.run(["powershell", "-Command", "Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | Select-Object -ExpandProperty Name"], capture_output=True, text=True)
    interfaces = result.stdout.strip().split('\n')
    return interfaces


def enable_all_ethernet_interfaces(interfaces):
    """
    与えられたすべてのイーサネットインターフェースを有効にします。
    """
    for interface in interfaces:
        subprocess.run(["powershell", "-Command", f"Enable-NetAdapter -Name \"{interface}\" -Confirm:$false"], capture_output=True, text=True)
        print(f"{interface}を有効にしました。")

def switch_ethernet_interface(interface_name, enable=True):
    """
    指定されたイーサネットインターフェースを有効または無効にします。
    enableパラメータがTrueの場合は有効に、Falseの場合は無効にします。
    """
    action = "Enable-NetAdapter" if enable else "Disable-NetAdapter"
    subprocess.run(["powershell", "-Command", f"{action} -Name \"{interface_name}\" -Confirm:$false"], capture_output=True, text=True)
    state = "有効" if enable else "無効"
    print(f"{interface_name}を{state}にしました。")
    
    # ログファイルにインターフェースの切り替え履歴を記録
    log_message = f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: {interface_name}を{state}にしました。\n"
    with open("C:\\Users\\100ca\\Documents\\PyCode\\internet\\log\\change_log.txt", "a", encoding='utf-8') as log_file:
        log_file.write(log_message)

def measure_speed(interface_name):
    """
    指定されたイーサネットインターフェースのインターネット速度（ダウンロードとアップロード）を測定します。
    """
    st = speedtest.Speedtest()
    st.download()
    st.upload()
    download_speed = round(st.results.dict()['download'] / 1_000_000, 1)
    upload_speed = round(st.results.dict()['upload'] / 1_000_000, 1)
    print(f"ダウンロード速度: {download_speed} Mbps, アップロード速度: {upload_speed} Mbps")
    return download_speed, upload_speed

def log_results(interface_name, download_speed, upload_speed):
    """
    インターネット速度の測定結果をログファイルとCSVファイルに記録します。
    """
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"{timestamp}: {interface_name}に更新しました。ダウンロード速度: {download_speed} Mbps, アップロード速度: {upload_speed} Mbps\n"
    print(log_message)
    
    log_file_path = "C:\\Users\\100ca\\Documents\\PyCode\\internet\\log\\change_log.txt"
    csv_file_path = "C:\\Users\\100ca\\Documents\\PyCode\\internet\\log\\log.csv"
    
    with open(log_file_path, "a", encoding='utf-8') as log_file:
        log_file.write(log_message)
    
    with open(csv_file_path, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow([timestamp, interface_name, download_speed, upload_speed])

def main():
    """
    メイン関数では、以下のステップを実行します。
    1. すべてのイーサネットインターフェースを取得します。
    2. 取得したインターフェースを一時的に無効にします。
    3. 各インターフェースを順番に有効にし、インターネット速度を測定します。
    4. 測定結果をログに記録します。
    5. 最後に、すべてのインターフェースを再度有効にします。
    """
    interfaces = get_ethernet_interfaces()
    print("利用可能なイーサネットインターフェース:", interfaces)

#    for interface in interfaces:
#        switch_ethernet_interface(interface, enable=False)
    
    for interface in interfaces:
        switch_ethernet_interface(interface, enable=True)
        print("10秒間停止しています...")
        time.sleep(10)  
        print("測定中")
        download_speed, upload_speed = measure_speed(interface)
        log_results(interface, download_speed, upload_speed)
        switch_ethernet_interface(interface, enable=False)
    
    # 最後にすべてのインターフェースを再度有効にする
    for interface in interfaces:
        switch_ethernet_interface(interface, enable=True)

if __name__ == "__main__":
    main()