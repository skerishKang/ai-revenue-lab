#!/usr/bin/env bash
# One monitoring cycle: one pc_read probe per device. Both devices are always
# attempted so one PC's failure never hides the other PC's data; a failing or
# over-30s probe already printed its one journal warning line
# (PC_READ_METRICS WARN ...) and makes this unit fail for systemd visibility.
set -u
measure=/opt/padiem/pc-read-metrics/pc_read_measure.py
failed=0
python3 "$measure" run --device comp1 --label timer || failed=1
python3 "$measure" run --device comp2 --label timer || failed=1
exit "$failed"
