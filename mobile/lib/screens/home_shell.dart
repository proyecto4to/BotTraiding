// Authenticated shell: app bar with the Demo/Real chip + Material 3 bottom
// navigation between Dashboard / Strategies / Alerts / Settings.

import 'package:flutter/material.dart';

import '../state/app_scope.dart';
import 'alerts_screen.dart';
import 'dashboard_screen.dart';
import 'settings_screen.dart';
import 'strategies_screen.dart';

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int _index = 0;

  static const _titles = ['Dashboard', 'Strategies', 'Alerts', 'Settings'];

  @override
  Widget build(BuildContext context) {
    final settings = AppScope.of(context).settings;
    return ListenableBuilder(
      listenable: settings,
      builder: (context, _) {
        final live = settings.liveMode;
        return Scaffold(
          appBar: AppBar(
            title: Text(_titles[_index]),
            actions: [
              Padding(
                padding: const EdgeInsets.only(right: 12),
                child: Center(
                  child: Chip(
                    visualDensity: VisualDensity.compact,
                    side: BorderSide(
                      color: live
                          ? const Color(0xFFEF4444)
                          : const Color(0xFF4F46E5),
                    ),
                    label: Text(
                      live ? 'REAL' : 'DEMO',
                      style: TextStyle(
                        fontWeight: FontWeight.w700,
                        fontSize: 12,
                        color: live
                            ? const Color(0xFFEF4444)
                            : const Color(0xFFA5B4FC),
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
          body: IndexedStack(
            index: _index,
            children: const [
              DashboardScreen(),
              StrategiesScreen(),
              AlertsScreen(),
              SettingsScreen(),
            ],
          ),
          bottomNavigationBar: NavigationBar(
            selectedIndex: _index,
            onDestinationSelected: (index) => setState(() => _index = index),
            destinations: const [
              NavigationDestination(
                icon: Icon(Icons.dashboard_outlined),
                selectedIcon: Icon(Icons.dashboard),
                label: 'Dashboard',
              ),
              NavigationDestination(
                icon: Icon(Icons.auto_graph_outlined),
                selectedIcon: Icon(Icons.auto_graph),
                label: 'Strategies',
              ),
              NavigationDestination(
                icon: Icon(Icons.notifications_outlined),
                selectedIcon: Icon(Icons.notifications),
                label: 'Alerts',
              ),
              NavigationDestination(
                icon: Icon(Icons.settings_outlined),
                selectedIcon: Icon(Icons.settings),
                label: 'Settings',
              ),
            ],
          ),
        );
      },
    );
  }
}
