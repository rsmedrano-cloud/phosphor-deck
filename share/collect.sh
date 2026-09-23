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
