// Dashboard: equity/PnL/drawdown cards, circuit-breaker chip and the open
// positions list. Pull-to-refresh reloads from the gateway.

import 'package:flutter/material.dart';

import '../models/portfolio.dart';
import '../state/app_scope.dart';
import '../utils/format.dart';

const _green = Color(0xFF16A34A);
const _red = Color(0xFFEF4444);

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  @override
  void initState() {
    super.initState();
    // Defer the first load until after the first frame so notifyListeners
    // never fires while the tree is still building.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final scope = AppScope.of(context);
      if (scope.dashboard.portfolio == null && !scope.dashboard.loading) {
        scope.dashboard.load(scope.settings.accountId);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final scope = AppScope.of(context);
    final dashboard = scope.dashboard;
    return ListenableBuilder(
      listenable: dashboard,
      builder: (context, _) {
        return RefreshIndicator(
          onRefresh: () => dashboard.load(scope.settings.accountId),
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.all(16),
            children: [
              if (dashboard.loading && dashboard.portfolio == null)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 48),
                  child: Center(child: CircularProgressIndicator()),
                ),
              if (dashboard.error != null)
                _ErrorBanner(message: dashboard.error!),
              if (dashboard.breaker != null)
                Align(
                  alignment: Alignment.centerLeft,
                  child: Chip(
                    avatar: Icon(
                      dashboard.breaker!.isNormal
                          ? Icons.check_circle
                          : Icons.warning_amber,
                      size: 18,
                      color: dashboard.breaker!.isNormal ? _green : _red,
                    ),
                    label: Text('Circuit breaker: ${dashboard.breaker!.state}'),
                  ),
                ),
              if (dashboard.portfolio != null) ...[
                const SizedBox(height: 12),
                _statsGrid(dashboard.portfolio!),
                const SizedBox(height: 20),
                Text('Open positions',
                    style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                if (dashboard.portfolio!.positions.isEmpty)
                  const Card(
                    child: Padding(
                      padding: EdgeInsets.all(20),
                      child: Center(child: Text('No open positions')),
                    ),
                  )
                else
                  ...dashboard.portfolio!.positions.map(_positionTile),
              ],
            ],
          ),
        );
      },
    );
  }

  Widget _statsGrid(PortfolioState portfolio) {
    final currency = portfolio.account.currency;
    final drawdown = portfolio.drawdown.currentDrawdown;
    return Column(
      children: [
        Row(
          children: [
            _StatCard(
              label: 'Equity',
              value: fmtMoney(portfolio.account.equity, currency),
            ),
            const SizedBox(width: 10),
            _StatCard(
              label: 'Balance',
              value: fmtMoney(portfolio.account.balance, currency),
            ),
          ],
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            _StatCard(
              label: 'Unrealized PnL',
              value: fmtMoney(portfolio.unrealizedPnl, currency),
              color: _pnlColor(portfolio.unrealizedPnl),
            ),
            const SizedBox(width: 10),
            _StatCard(
              label: 'Daily PnL',
              value: fmtMoney(portfolio.pnlDaily, currency),
              color: _pnlColor(portfolio.pnlDaily),
            ),
          ],
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            _StatCard(
              label: 'Drawdown',
              value: fmtPct(drawdown),
              color: drawdown > 0 ? _red : null,
            ),
            const SizedBox(width: 10),
            _StatCard(
              label: 'Realized PnL',
              value: fmtMoney(portfolio.realizedPnl, currency),
              color: _pnlColor(portfolio.realizedPnl),
            ),
          ],
        ),
      ],
    );
  }

  Widget _positionTile(Position position) {
    return Card(
      child: ListTile(
        title: Text(position.symbol),
        subtitle: Text(
          'qty ${fmtNum(position.quantity, 4)} @ ${fmtMoney(position.averagePrice)}',
        ),
        trailing: Text(
          fmtMoney(position.unrealizedPnl),
          style: TextStyle(
            color: _pnlColor(position.unrealizedPnl),
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }

  static Color? _pnlColor(double value) {
    if (value > 0) return _green;
    if (value < 0) return _red;
    return null;
  }
}

class _StatCard extends StatelessWidget {
  const _StatCard({required this.label, required this.value, this.color});

  final String label;
  final String value;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: Theme.of(context).textTheme.labelSmall),
              const SizedBox(height: 4),
              Text(
                value,
                style: Theme.of(context)
                    .textTheme
                    .titleMedium
                    ?.copyWith(color: color, fontWeight: FontWeight.w600),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  const _ErrorBanner({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Card(
      color: _red.withOpacity(0.12),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          children: [
            const Icon(Icons.cloud_off, color: _red, size: 18),
            const SizedBox(width: 8),
            Expanded(child: Text(message)),
          ],
        ),
      ),
    );
  }
}
