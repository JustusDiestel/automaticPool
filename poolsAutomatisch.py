import subprocess

def get_valid_disk_ids():
    """
    Führt Bash-Code aus, holt alle /dev/sdX Disks mit 18-stelliger Logical Unit ID
    und gibt NUR die ID zurück (ohne /dev, ohne scsi-)
    """
    cmd = r'''
    for dev in /dev/sd*; do
      [[ "$dev" =~ [0-9] ]] && continue
      id=$(smartctl -i "$dev" | grep 'Logical Unit id' | awk '{print $4}')
      if [[ ${#id} -eq 18 ]]; then
        echo "${id/0x/}"  # Entfernt 0x-Präfix
      fi
    done
    '''
    result = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)

    if result.returncode != 0:
        print("Fehler beim Abrufen der Logical Unit IDs:")
        print(result.stderr)
        return []

    ids = result.stdout.strip().splitlines()
    return ids


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

        zpool_cmd = "zpool create mypool \\\n  " + " \\\n  ".join(vdev_parts)

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


if __name__ == "__main__":
    disk_ids = get_valid_disk_ids()

    if not disk_ids:
        print("Keine gültigen Disks gefunden.")
        exit(1)

    configs = generate_draid2_configs(disk_ids)

    for cfg in configs:
        print(cfg["zpool_create_cmd"])
        print("------")
