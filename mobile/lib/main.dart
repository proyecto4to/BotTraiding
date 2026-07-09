// TradingPlatform mobile app - Fase 1 skeleton.
// No business logic: a placeholder screen only. The app is expected to
// consume exclusively the `gateway` service (see docs/ARCHITECTURE.md).
import 'package:flutter/material.dart';

void main() {
  runApp(const TradingPlatformApp());
}

class TradingPlatformApp extends StatelessWidget {
  const TradingPlatformApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'TradingPlatform',
      theme: ThemeData(primarySwatch: Colors.blue, useMaterial3: true),
      home: const HomeScreen(),
    );
  }
}

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('TradingPlatform')),
      body: const Center(
        child: Padding(
          padding: EdgeInsets.all(24.0),
          child: Text(
            'TradingPlatform Dashboard\n\nFase 1 skeleton placeholder screen.',
            textAlign: TextAlign.center,
          ),
        ),
      ),
    );
  }
}
