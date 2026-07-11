// Alerts: risk events list (rejections, circuit-breaker trips, limit
// changes). The backend list endpoint is pending; until it responds the
// screen shows a calm explanatory empty state.

import 'package:flutter/material.dart';

import '../models/risk.dart';
import '../state/app_scope.dart';

class AlertsScreen extends StatefulWidget {
  const AlertsScreen({super.key});

  @override
  State<AlertsScreen> createState() => _AlertsScreenState();
}

class _AlertsScreenState extends State<AlertsScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final scope = AppScope.of(context);
      if (scope.alerts.events.isEmpty && !scope.alerts.loading) {
        scope.alerts.load(scope.settings.accountId);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final scope = AppScope.of(context);
    final alerts = scope.alerts;
    return ListenableBuilder(
      listenable: alerts,
      builder: (context, _) {
        return RefreshIndicator(
          onRefresh: () => alerts.load(scope.settings.accountId),
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.all(16),
            children: [
              if (alerts.loading && alerts.events.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 48),
                  child: Center(child: CircularProgressIndicator()),
                )
              else if (alerts.events.isEmpty)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 48),
                  child: Center(
                    child: Column(
                      children: [
                        const Icon(Icons.notifications_none, size: 40),
                        const SizedBox(height: 12),
                        Text(
                          alerts.unavailable
                              ? 'The risk-events feed is not available yet.\n'
                                  'Pull to refresh once the backend lands.'
                              : 'No alerts. Risk rejections and circuit-breaker\n'
                                  'trips will appear here.',
                          textAlign: TextAlign.center,
                        ),
                      ],
                    ),
                  ),
                )
              else
                ...alerts.events.map(_eventTile),
            ],
          ),
        );
      },
    );
  }

  Widget _eventTile(RiskEvent event) {
    final type = event.eventType.toLowerCase();
    final isSevere = type.contains('circuit_breaker') || type.contains('halt');
    final isWarning = type.contains('reject');
    return Card(
      child: ListTile(
        leading: Icon(
          isSevere
              ? Icons.error_outline
              : isWarning
                  ? Icons.warning_amber
                  : Icons.info_outline,
          color: isSevere
              ? const Color(0xFFEF4444)
              : isWarning
                  ? const Color(0xFFD97706)
                  : null,
        ),
        title: Text(event.eventType),
        subtitle: Text(
          '${event.createdAt ?? ''}\n${event.payload}',
          maxLines: 3,
          overflow: TextOverflow.ellipsis,
        ),
        isThreeLine: true,
      ),
    );
  }
}
