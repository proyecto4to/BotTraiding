// Settings: gateway URL, account id, and the prominent Demo/Real indicator.
// The Demo/Real switch is a display preference with an explicit warning
// dialog — live execution is gated server-side by the execution-engine.

import 'package:flutter/material.dart';

import '../state/app_scope.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final TextEditingController _gatewayUrl;
  late final TextEditingController _accountId;

  @override
  void initState() {
    super.initState();
    _gatewayUrl = TextEditingController();
    _accountId = TextEditingController();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final settings = AppScope.of(context).settings;
    if (_gatewayUrl.text.isEmpty) _gatewayUrl.text = settings.gatewayUrl;
    if (_accountId.text.isEmpty) _accountId.text = settings.accountId;
  }

  @override
  void dispose() {
    _gatewayUrl.dispose();
    _accountId.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final scope = AppScope.of(context);
    final settings = scope.settings;
    return ListenableBuilder(
      listenable: settings,
      builder: (context, _) {
        final live = settings.liveMode;
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Card(
              color: live
                  ? const Color(0xFFEF4444).withOpacity(0.15)
                  : const Color(0xFF4F46E5).withOpacity(0.15),
              child: ListTile(
                leading: Icon(
                  live ? Icons.warning_amber : Icons.science_outlined,
                  color: live ? const Color(0xFFEF4444) : null,
                ),
                title: Text(
                  live ? 'REAL — LIVE TRADING' : 'DEMO — PAPER TRADING',
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
                subtitle: const Text(
                  'Execution mode is enforced server-side; this indicator '
                  'reflects the mode used when composing orders.',
                ),
                trailing: Switch(
                  value: live,
                  onChanged: (next) => _onModeChanged(context, next),
                ),
              ),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _gatewayUrl,
              keyboardType: TextInputType.url,
              autocorrect: false,
              decoration: const InputDecoration(
                labelText: 'Gateway URL',
                helperText:
                    'All traffic goes through the gateway (default http://10.0.2.2:8000 for the Android emulator).',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _accountId,
              autocorrect: false,
              decoration: const InputDecoration(labelText: 'Account id'),
            ),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: () {
                settings.setGatewayUrl(_gatewayUrl.text);
                settings.setAccountId(_accountId.text);
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Settings applied.')),
                );
              },
              child: const Text('Apply'),
            ),
            const SizedBox(height: 24),
            Text(
              'Signed in as ${scope.auth.user?.email ?? '—'}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              icon: const Icon(Icons.logout),
              label: const Text('Log out'),
              onPressed: scope.auth.logout,
            ),
          ],
        );
      },
    );
  }

  Future<void> _onModeChanged(BuildContext context, bool next) async {
    final settings = AppScope.of(context).settings;
    if (!next) {
      settings.setLiveMode(false);
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Switch to REAL (live) mode?'),
        content: const Text(
          'Orders composed in REAL mode target live broker accounts with '
          'real money. Every order still passes the risk engine, but fills '
          'are irreversible. The mandatory progression is backtest → paper '
          '→ real.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xFFEF4444),
            ),
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('I understand — switch'),
          ),
        ],
      ),
    );
    if (confirmed == true) settings.setLiveMode(true);
  }
}
