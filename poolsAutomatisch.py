import subprocess
import time
from datetime import datetime

POOL_NAME = "mypool"

def run_cmd(cmd, check=True):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"[FEHLER] Befehl fehlgeschlagen: {cmd}")
        print(result.stderr)
        raise Exception("Fehler bei Kommandoausführung")
    return result.stdout.strip()

def get_valid_disk_ids():
    cmd = r'''
    for dev in /dev/sd*; do
      [[ "$dev" =~ [0-9] ]] && continue
      id=$(smartctl -i "$dev" | grep 'Logical Unit id' | awk '{print $4}')
      if [[ ${#id} -eq 18 ]]; then
        echo "${id/0x/}"
      fi
    done
    '''
    result = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    if result.returncode != 0:
        print("Fehler beim Abrufen der Logical Unit IDs:")
        print(result.stderr)
        return []
    return result.stdout.strip().splitlines()

def generate_draid2_configs(disk_ids, min_children=4):
    total_disks = len(disk_ids) - 1  # Eine als Ersatz freihalten!
    configs = []

    for vdevs in range(1, total_disks + 1):
        if total_disks % vdevs != 0:
            continue

        children = total_disks // vdevs
        if children < min_children:
            continue

        spares = 1
        parity = 2
        data = children - parity - spares
        if data < 1:
            continue

        vdev_config = f"draid2:{children}:{spares}:{data}"
        vdev_parts = []
        for i in range(vdevs):
            start = i * children
            end = start + children
            vdev_devs = " ".join(f"/dev/disk/by-id/{disk_ids[j]}" for j in range(start, end))
            vdev_parts.append(f"{vdev_config} {vdev_devs}")

        zpool_cmd = f"zpool create {POOL_NAME} \\\n  " + " \\\n  ".join(vdev_parts)

        configs.append({
            "vdevs": vdevs,
            "children": children,
            "spares": spares,
            "parity": parity,
            "data": data,
            "zfs_syntax": vdev_config,
            "zpool_create_cmd": zpool_cmd,
            "used_disks": disk_ids[:total_disks],
            "spare_disk": disk_ids[total_disks]  # Reserve-Disk
        })

    return configs

def create_pool(pool_cmd):
    print("[INFO] Erstelle Pool...")
    run_cmd(pool_cmd)

def simulate_resilver(pool_name, used_disks, spare_disk):
    failed_disk = used_disks[0]
    failed_path = f"/dev/disk/by-id/{failed_disk}"
    replacement_path = f"/dev/disk/by-id/{spare_disk}"

    print(f"[INFO] Nehme Disk offline: {failed_path}")
    run_cmd(f"zpool offline {pool_name} {failed_path}")
    time.sleep(1)

    print(f"[INFO] Ersetze durch Ersatz-Disk: {replacement_path}")
    run_cmd(f"zpool replace {pool_name} {failed_path} {replacement_path}")
    time.sleep(2)

    print("[INFO] Warte auf Resilvering...")
    start_time = time.time()
    while True:
        status = run_cmd(f"zpool status {pool_name}", check=False)
        if "resilver in progress" in status:
            time.sleep(2)
        else:
            break
    end_time = time.time()
    duration = end_time - start_time

    return duration, status

def delete_pool(pool_name):
    print("[INFO] Lösche Pool...")
    run_cmd(f"zpool destroy {pool_name}")

def main():
    disk_ids = get_valid_disk_ids()
    if len(disk_ids) < 5:
        print("Nicht genug Disks verfügbar!")
        return

    configs = generate_draid2_configs(disk_ids)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logfile = f"resilver_tests_{timestamp}.log"

    for i, cfg in enumerate(configs):
        print(f"\n[TEST {i+1}/{len(configs)}] {cfg['zfs_syntax']}")
        try:
            create_pool(cfg["zpool_create_cmd"])
            duration, status = simulate_resilver(POOL_NAME, cfg["used_disks"], cfg["spare_disk"])
            delete_pool(POOL_NAME)

            with open(logfile, "a") as f:
                f.write(f"--- Test {i+1} ---\n")
                f.write(f"Konfiguration: {cfg['zfs_syntax']}\n")
                f.write(f"VDEVs: {cfg['vdevs']}, Data: {cfg['data']}, Children: {cfg['children']}\n")
                f.write(f"Resilver-Zeit: {duration:.2f} Sekunden\n")
                f.write(status + "\n\n")

        except Exception as e:
            print(f"[FEHLER] Test abgebrochen: {e}")
            try:
                delete_pool(POOL_NAME)
            except:
                pass
            continue

    print(f"\n✅ Alle Tests abgeschlossen. Ergebnisse in {logfile}")


if __name__ == "__main__":
    main()

