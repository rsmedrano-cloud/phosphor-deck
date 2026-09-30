#!/bin/sh
# Phosphor fleet collector: piped over ssh (`ssh host sh -s`), one pass,
# KEY=VALUE lines out. POSIX sh and /proc only, so nothing gets installed.
read -r _ u n s i w x y z rest < /proc/stat
t1=$((u+n+s+i+w+x+y)); d1=$((i+w))
sleep 0.4
read -r _ u n s i w x y z rest < /proc/stat
t2=$((u+n+s+i+w+x+y)); d2=$((i+w))
dt=$((t2-t1)); di=$((d2-d1))
if [ "$dt" -gt 0 ]; then echo "CPU=$(( (dt-di)*100/dt ))"; else echo "CPU=0"; fi
awk '/MemTotal/{t=$2}/MemAvailable/{a=$2}END{printf "MEMU=%d\nMEMT=%d\n",(t-a)/1024,t/1024}' /proc/meminfo
awk '{printf "LOAD=%s %s %s\n",$1,$2,$3}' /proc/loadavg
awk '{d=$1/86400; h=($1%86400)/3600; if(d>=1) printf "UP=%dd\n",d; else printf "UP=%dh\n",h}' /proc/uptime
df -h --output=source,target,pcent,size -x tmpfs -x devtmpfs -x overlay -x squashfs -x efivarfs -x fuse.rclone -x fuse.sshfs -x fuse 2>/dev/null \
  | tail -n +2 | sort -k2,2 \
  | awk '$2 ~ /^\/(sys|proc|run|dev|boot|etc)/ {next} $4 !~ /[GT]$/ {next} seen[$1]++ {next} {gsub("%","",$3); print "MNT=" $2 "|" $3 "|" $4}'
# A machine rarely dies outright; a key service crashing (jellyfin,
# postgresql, tailscaled) or a security update leaving a reboot pending is
# the more common self-hosting failure. Both are near-free to check.
if command -v systemctl >/dev/null 2>&1; then
  echo "SVCFAIL=$(systemctl --failed --quiet --no-legend 2>/dev/null | wc -l)"
fi
[ -f /var/run/reboot-required ] && echo "REBOOT=1"

if command -v docker >/dev/null 2>&1 && docker ps -q >/dev/null 2>&1; then
  echo "CTR=docker|$(docker ps -q 2>/dev/null|wc -l)|$(docker ps -aq -f status=exited 2>/dev/null|wc -l)"
elif command -v podman >/dev/null 2>&1; then
  echo "CTR=podman|$(podman ps -q 2>/dev/null|wc -l)|$(podman ps -aq -f status=exited 2>/dev/null|wc -l)"
fi

# GPU, three levels: nvidia-smi (rich data) -> amdgpu sysfs -> just the
# vendor id. The last one needs no tools at all.
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu \
    --format=csv,noheader,nounits 2>/dev/null | while IFS=, read -r n u mu mt t; do
      printf "GPU=%s|%s|%s|%s|%s\n" "$(echo "$n" | sed 's/^ *//;s/ *$//')" \
        "$(echo "$u" | tr -d ' ')" "$(echo "$mu" | tr -d ' ')" \
        "$(echo "$mt" | tr -d ' ')" "$(echo "$t" | tr -d ' ')"
    done
else
  for c in /sys/class/drm/card[0-9]; do
    [ -e "$c/device/vendor" ] || continue
    case "$(cat "$c/device/vendor" 2>/dev/null)" in
      0x1002) n=AMD ;; 0x10de) n=NVIDIA ;; 0x8086) n="Intel" ;; *) n=GPU ;;
    esac
    u=""; mu=""; mt=""; t=""
    [ -r "$c/device/gpu_busy_percent" ] && u=$(cat "$c/device/gpu_busy_percent")
    if [ -r "$c/device/mem_info_vram_used" ]; then
      mu=$(( $(cat "$c/device/mem_info_vram_used") / 1048576 ))
      mt=$(( $(cat "$c/device/mem_info_vram_total") / 1048576 ))
    fi
    for h in "$c"/device/hwmon/hwmon*/temp1_input; do
      [ -r "$h" ] && t=$(( $(cat "$h") / 1000 )) && break
    done
    printf "GPU=%s|%s|%s|%s|%s\n" "$n" "$u" "$mu" "$mt" "$t"
  done
fi

# Sensors the kernel already exposes (sysfs, no tools): the CPU's own
# temperature (its hottest reading) and a laptop's battery -- an old
# laptop is a common brain. PHOSPHOR_SYS only moves /sys for the tests.
S=${PHOSPHOR_SYS:-/sys}
t=0
for h in "$S"/class/hwmon/hwmon*; do
  case "$(cat "$h/name" 2>/dev/null)" in
    coretemp|k10temp|zenpower|cpu_thermal|soc_thermal) ;;
    *) continue ;;
  esac
  for f in "$h"/temp*_input; do
    v=$(cat "$f" 2>/dev/null); [ "${v:-0}" -gt "$t" ] 2>/dev/null && t=$v
  done
done
if [ "$t" -eq 0 ]; then
  for z in "$S"/class/thermal/thermal_zone*; do
    case "$(cat "$z/type" 2>/dev/null)" in
      x86_pkg_temp|cpu-thermal|cpu_thermal|soc-thermal|soc_thermal) ;;
      *) continue ;;
    esac
    v=$(cat "$z/temp" 2>/dev/null); [ "${v:-0}" -gt "$t" ] 2>/dev/null && t=$v
  done
fi
[ "$t" -gt 0 ] && echo "TEMP=$((t/1000))"
for b in "$S"/class/power_supply/*; do
  [ "$(cat "$b/type" 2>/dev/null)" = Battery ] || continue
  [ "$(cat "$b/scope" 2>/dev/null)" = Device ] && continue   # a mouse, a headset
  [ -r "$b/capacity" ] || continue
  echo "BAT=$(cat "$b/capacity")|$(cat "$b/status" 2>/dev/null)"
  break
done

# SMART: a disk that says it's failing, before it does. Only where
# smartctl answers without a password (root, or a NOPASSWD sudoers rule
# for it; sudo is only tried by a user in sudo/wheel/admin, never one sudo
# would report). `-n standby` never spins up a sleeping disk. Asked every
# 30 minutes at most, not every poll: the answer waits in a small file on
# that machine, and "not allowed here" waits a day.
if command -v smartctl >/dev/null 2>&1; then
  c=${XDG_RUNTIME_DIR:-$HOME/.cache}
  mkdir -p "$c" 2>/dev/null; c=$c/phosphor-smart
  age=30; [ -f "$c" ] && [ ! -s "$c" ] && age=1440
  if [ ! -f "$c" ] || [ -z "$(find "$c" -mmin -$age 2>/dev/null)" ]; then
    if [ "$(id -u)" = 0 ]; then sc=smartctl
    elif id -Gn 2>/dev/null | grep -qwE 'sudo|wheel|admin'; then sc="sudo -n smartctl"
    else sc=smartctl; fi
    f=0; n=0; out=-
    for dev in $(ls "$S"/block 2>/dev/null); do
      case "$dev" in loop*|ram*|zram*|dm-*|md*|sr*|fd*|nbd*) continue ;; esac
      o=$($sc -H -n standby "/dev/$dev" 2>&1); r=$?
      case "$o" in
        *STANDBY*|*SLEEP*) continue ;;
        *"ermission denied"*|*"password is required"*|*"not allowed"*|*"sudoers"*) out=""; break ;;
      esac
      [ $((r & 2)) -ne 0 ] && continue   # no SMART there (a USB bridge, a virtual disk)
      n=$((n+1)); [ $((r & 8)) -ne 0 ] && f=$((f+1))
    done
    [ -n "$out" ] && [ "$n" -gt 0 ] && out="SMART=$f|$n"
    if [ -n "$out" ]; then echo "$out" > "$c"; else : > "$c"; fi 2>/dev/null
  fi
  grep '^SMART=' "$c" 2>/dev/null
fi
exit 0
