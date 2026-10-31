import React, {useCallback, useEffect, useState} from 'react';
import {ActivityIndicator, Pressable, StyleSheet, Text, View} from 'react-native';

import {padiemApi} from '../api/padiem';
import {PadiemTheme, radius, spacing} from '../ui/theme';

interface Props {
  theme: PadiemTheme;
  conversationId: string | null;
  deviceId: string | null;
  onSelectDevice: (deviceId: string | null) => void;
  labels: {
    connected: string;
    disconnected: string;
    connect: string;
    refresh: string;
    device: string;
    noDevice: string;
    runs: string;
    noRuns: string;
    approve: string;
    reject: string;
  };
}

interface RunSummary {
  id: string;
  status: string;
  title: string;
  needsApproval: boolean;
}

/**
 * Claw connection panel.
 *
 * The PC state, the device list and the run list all come from the existing
 * Claw routes. The app never decides whether a PC is reachable or whether a
 * run may proceed: the server is the only authority for both, so this panel
 * only renders what the server already reported.
 */
export function ClawStatusBar({
  theme,
  conversationId,
  deviceId,
  onSelectDevice,
  labels,
}: Props): React.JSX.Element {
  const [available, setAvailable] = useState<boolean | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  const [devices, setDevices] = useState<Array<{device_id: string; label?: string | null; state?: string}>>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const access = await padiemApi.clawLocalAccess(conversationId);
      const isAvailable = access.available === true || access.ok === true;
      setAvailable(isAvailable);
      setReason(typeof access.reason === 'string' ? access.reason : null);

      const directory = await padiemApi.clawDevices();
      const rawDevices = Array.isArray(directory.devices)
        ? (directory.devices as Array<{device_id?: string; label?: string | null; state?: string}>)
        : [];
      setDevices(
        rawDevices
          .filter(item => typeof item.device_id === 'string')
          .map(item => ({
            device_id: item.device_id as string,
            label: item.label ?? null,
            state: item.state,
          })),
      );

      const runHistory = await padiemApi.clawRuns();
      const rawRuns = Array.isArray(runHistory.runs)
        ? (runHistory.runs as Array<Record<string, unknown>>)
        : [];
      setRuns(
        rawRuns.slice(0, 5).map(item => {
          const status = typeof item.status === 'string' ? item.status : 'unknown';
          return {
            id: typeof item.run_id === 'string' ? item.run_id : String(item.id ?? ''),
            status,
            title:
              typeof item.title === 'string'
                ? item.title
                : typeof item.summary === 'string'
                  ? (item.summary as string)
                  : status,
            needsApproval: status === 'awaiting_approval' || status === 'pending_approval',
          };
        }),
      );
    } catch {
      setAvailable(false);
    } finally {
      setBusy(false);
    }
  }, [conversationId]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleConnect = useCallback(async () => {
    setBusy(true);
    try {
      await padiemApi.clawConnect();
    } catch {
      // The server decides; the panel just refreshes afterwards.
    } finally {
      setBusy(false);
      await load();
    }
  }, [load]);

  const handleDecision = useCallback(
    async (runId: string, decision: 'approve' | 'reject') => {
      if (!runId) {
        return;
      }
      setBusy(true);
      try {
        await padiemApi.clawApprovalDecision(runId, decision);
      } catch {
        // Ignored: the run list below shows the server's own verdict.
      } finally {
        setBusy(false);
        await load();
      }
    },
    [load],
  );

  const connected = available === true;

  return (
    <View style={[styles.container, {backgroundColor: theme.surface, borderBottomColor: theme.border}]}>
      <View style={styles.row}>
        <View
          style={[
            styles.chip,
            {
              backgroundColor: connected ? theme.accentSoft : theme.surfaceRaised,
              borderColor: connected ? theme.accent : theme.border,
            },
          ]}>
          <View
            style={[
              styles.dot,
              {backgroundColor: connected ? theme.success : theme.textMuted},
            ]}
          />
          <Text
            style={[
              styles.chipText,
              {color: connected ? theme.accent : theme.textMuted},
            ]}>
            {connected ? labels.connected : labels.disconnected}
          </Text>
        </View>

        <Text style={[styles.deviceText, {color: theme.textMuted}]} numberOfLines={1}>
          {deviceId
            ? `${labels.device}: ${devices.find(d => d.device_id === deviceId)?.label ?? deviceId}`
            : labels.noDevice}
        </Text>

        {busy ? (
          <ActivityIndicator size="small" color={theme.textMuted} />
        ) : (
          <>
            <Pressable accessibilityRole="button" onPress={() => void handleConnect()}>
              <Text style={[styles.action, {color: theme.accent}]}>{labels.connect}</Text>
            </Pressable>
            <Pressable accessibilityRole="button" onPress={() => void load()}>
              <Text style={[styles.action, {color: theme.textMuted}]}>{labels.refresh}</Text>
            </Pressable>
          </>
        )}
        <Pressable
          accessibilityRole="button"
          onPress={() => setExpanded(value => !value)}
          hitSlop={8}>
          <Text style={[styles.action, {color: theme.textMuted}]}>
            {expanded ? '▾' : '▸'}
          </Text>
        </Pressable>
      </View>

      {reason && !connected ? (
        <Text style={[styles.reason, {color: theme.textMuted}]} numberOfLines={1}>
          {reason}
        </Text>
      ) : null}

      {expanded ? (
        <View style={styles.expanded}>
          {devices.length > 0 ? (
            <View style={styles.deviceRow}>
              {devices.map(device => {
                const active = device.device_id === deviceId;
                return (
                  <Pressable
                    key={device.device_id}
                    accessibilityRole="button"
                    onPress={() => onSelectDevice(active ? null : device.device_id)}
                    style={[
                      styles.deviceChip,
                      {
                        backgroundColor: active ? theme.accentSoft : theme.surfaceRaised,
                        borderColor: active ? theme.accent : theme.border,
                      },
                    ]}>
                    <Text
                      style={[
                        styles.deviceChipText,
                        {color: active ? theme.accent : theme.textMuted},
                      ]}>
                      {device.label ?? device.device_id}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          ) : null}

          <Text style={[styles.runsTitle, {color: theme.textMuted}]}>{labels.runs}</Text>
          {runs.length === 0 ? (
            <Text style={[styles.reason, {color: theme.textMuted}]}>{labels.noRuns}</Text>
          ) : (
            runs.map(run => (
              <View key={run.id} style={styles.runRow}>
                <Text style={[styles.runText, {color: theme.text}]} numberOfLines={1}>
                  {run.title}
                </Text>
                {run.needsApproval ? (
                  <View style={styles.decisionRow}>
                    <Pressable
                      accessibilityRole="button"
                      onPress={() => void handleDecision(run.id, 'approve')}>
                      <Text style={[styles.action, {color: theme.success}]}>
                        {labels.approve}
                      </Text>
                    </Pressable>
                    <Pressable
                      accessibilityRole="button"
                      onPress={() => void handleDecision(run.id, 'reject')}>
                      <Text style={[styles.action, {color: theme.danger}]}>
                        {labels.reject}
                      </Text>
                    </Pressable>
                  </View>
                ) : (
                  <Text style={[styles.runStatus, {color: theme.textMuted}]}>
                    {run.status}
                  </Text>
                )}
              </View>
            ))
          )}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    borderBottomWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  row: {flexDirection: 'row', alignItems: 'center'},
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: 4,
    marginRight: spacing.sm,
  },
  dot: {width: 7, height: 7, borderRadius: 4, marginRight: 6},
  chipText: {fontSize: 12, fontWeight: '600'},
  deviceText: {flex: 1, fontSize: 12},
  action: {fontSize: 12, fontWeight: '600', marginLeft: spacing.md},
  reason: {fontSize: 11, marginTop: 6},
  expanded: {marginTop: spacing.sm},
  deviceRow: {flexDirection: 'row', flexWrap: 'wrap'},
  deviceChip: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: 5,
    marginRight: spacing.sm,
    marginBottom: spacing.sm,
  },
  deviceChipText: {fontSize: 12},
  runsTitle: {fontSize: 11, marginBottom: 4, marginTop: spacing.xs},
  runRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 4,
  },
  runText: {flex: 1, fontSize: 13, marginRight: spacing.md},
  runStatus: {fontSize: 11},
  decisionRow: {flexDirection: 'row'},
});
