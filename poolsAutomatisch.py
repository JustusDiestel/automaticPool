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


def create_pool(pool_cmd):
    print(f"[INFO] Erstelle Pool:\n{pool_cmd}")
    run_cmd(pool_cmd)


def simulate_resilver(pool_name):
    print("[INFO] Starte Resilver-Simulation (Scrub)...")
    run_cmd(f"zpool scrub {pool_name}")
    time.sleep(5)  # optional: gib dem Scrub etwas Zeit

    print("[INFO] Warte auf Scrub-Ende...")
    while True:
        status = run_cmd(f"zpool status {pool_name}")
        if "scrub in progress" in status:
            time.sleep(2)
        else:
            break

    return status


def delete_pool(pool_name):
    print(f"[INFO] Pool {pool_name} wird gelöscht...")
    run_cmd(f"zpool destroy {pool_name}")


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
    total_disks = len(disk_ids)
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

        rg_possible = [i for i in range(1, data + 1) if data % i == 0]
        vdev_config = f"draid2:{children}:{spares}:{data}"
        vdev_parts = []

        for i in range(vdevs):
            start = i * children
            end = start + children
            vdev_devs = " ".join(f"/dev/disk/by-id/{id_}" for id_ in disk_ids[start:end])
            vdev_parts.append(f"{vdev_config} {vdev_devs}")

        zpool_cmd = f"zpool create {POOL_NAME} \\\n  " + " \\\n  ".join(vdev_parts)

        configs.append({
            "vdevs": vdevs,
            "children": children,
            "spares_per_vdev": spares,
            "parity": parity,
            "data": data,
            "redundancy_groups": rg_possible,
            "zfs_syntax": vdev_config,
            "zpool_create_cmd": zpool_cmd
        })

    return configs


def main():
    disk_ids = get_valid_disk_ids()
    if not disk_ids:
        print("Keine gültigen Disks gefunden.")
        return

    configs = generate_draid2_configs(disk_ids)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logfile = f"resilver_results_{timestamp}.log"

    for i, cfg in enumerate(configs):
        print(f"\n[TEST {i+1}/{len(configs)}] Konfiguration: {cfg['zfs_syntax']}")
        try:
            create_pool(cfg["zpool_create_cmd"])
            result = simulate_resilver(POOL_NAME)
            delete_pool(POOL_NAME)

            with open(logfile, "a") as f:
                f.write(f"--- TEST {i+1} ---\n")
                f.write(f"Konfiguration: {cfg['zfs_syntax']}\n")
                f.write(result + "\n\n")

        except Exception as e:
            print(f"[WARNUNG] Test fehlgeschlagen: {e}")
            continue

    print(f"\n✅ Alle Tests abgeschlossen. Ergebnisse in {logfile}")


if __name__ == "__main__":
    main()
