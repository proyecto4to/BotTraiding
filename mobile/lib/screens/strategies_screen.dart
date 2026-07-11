// Strategies: list with enable/disable switches (PATCH via the gateway).

import 'package:flutter/material.dart';

import '../state/app_scope.dart';

class StrategiesScreen extends StatefulWidget {
  const StrategiesScreen({super.key});

  @override
  State<StrategiesScreen> createState() => _StrategiesScreenState();
}

class _StrategiesScreenState extends State<StrategiesScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final strategies = AppScope.of(context).strategies;
      if (strategies.strategies.isEmpty && !strategies.loading) {
        strategies.load();
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context).strategies;
    return ListenableBuilder(
      listenable: state,
      builder: (context, _) {
        return RefreshIndicator(
          onRefresh: state.load,
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.all(16),
            children: [
              if (state.loading && state.strategies.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 48),
                  child: Center(child: CircularProgressIndicator()),
                )
              else if (state.strategies.isEmpty)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 48),
                  child: Center(
                    child: Text(
                      state.error ?? 'No strategies found',
                      textAlign: TextAlign.center,
                    ),
                  ),
                )
              else
                ...state.strategies.map(
                  (s) => Card(
                    child: SwitchListTile(
                      title: Text(s.name),
                      subtitle: Text(
                        '${s.category} · ${s.markets.join(', ')} · ${s.timeframes.join(', ')}',
                      ),
                      value: s.enabled,
                      onChanged: state.togglingKey == s.key
                          ? null
                          : (enabled) async {
                              final failure = await state.toggle(s, enabled);
                              if (failure != null && context.mounted) {
                                ScaffoldMessenger.of(context).showSnackBar(
                                  SnackBar(content: Text(failure)),
                                );
                              }
                            },
                    ),
                  ),
                ),
            ],
          ),
        );
      },
    );
  }
}
