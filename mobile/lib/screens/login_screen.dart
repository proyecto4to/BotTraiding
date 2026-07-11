// Login: email + password -> POST /api/auth/login; when the account has MFA
// the gateway returns mfa_required and the screen switches to the TOTP step
// (POST /api/auth/login/mfa).

import 'package:flutter/material.dart';

import '../state/app_scope.dart';
import '../state/auth_state.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _code = TextEditingController();

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    _code.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final auth = AppScope.of(context).auth;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 380),
              child: ListenableBuilder(
                listenable: auth,
                builder: (context, _) {
                  final submitting = auth.status == AuthStatus.submitting;
                  final mfaStep = auth.status == AuthStatus.mfaRequired;
                  return Card(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Row(
                            children: [
                              Icon(Icons.candlestick_chart,
                                  color: Theme.of(context).colorScheme.primary),
                              const SizedBox(width: 8),
                              const Text(
                                'TradingPlatform',
                                style: TextStyle(
                                    fontSize: 18, fontWeight: FontWeight.w700),
                              ),
                            ],
                          ),
                          const SizedBox(height: 20),
                          if (auth.error != null) ...[
                            Text(
                              auth.error!,
                              style: TextStyle(
                                  color: Theme.of(context).colorScheme.error),
                            ),
                            const SizedBox(height: 12),
                          ],
                          if (!mfaStep) ..._credentialFields(auth, submitting)
                          else ..._mfaFields(auth, submitting),
                        ],
                      ),
                    ),
                  );
                },
              ),
            ),
          ),
        ),
      ),
    );
  }

  List<Widget> _credentialFields(AuthState auth, bool submitting) {
    return [
      TextField(
        controller: _email,
        keyboardType: TextInputType.emailAddress,
        autocorrect: false,
        decoration: const InputDecoration(labelText: 'Email'),
      ),
      const SizedBox(height: 12),
      TextField(
        controller: _password,
        obscureText: true,
        decoration: const InputDecoration(labelText: 'Password'),
        onSubmitted: (_) => _submitCredentials(auth),
      ),
      const SizedBox(height: 20),
      FilledButton(
        onPressed: submitting ? null : () => _submitCredentials(auth),
        child: Text(submitting ? 'Signing in…' : 'Sign in'),
      ),
    ];
  }

  List<Widget> _mfaFields(AuthState auth, bool submitting) {
    return [
      const Text(
        'Multi-factor authentication is enabled. '
        'Enter the 6-digit code from your authenticator app.',
      ),
      const SizedBox(height: 12),
      TextField(
        controller: _code,
        keyboardType: TextInputType.number,
        maxLength: 8,
        autofocus: true,
        decoration: const InputDecoration(labelText: 'TOTP code'),
        onSubmitted: (_) => _submitCode(auth),
      ),
      const SizedBox(height: 8),
      FilledButton(
        onPressed: submitting ? null : () => _submitCode(auth),
        child: Text(submitting ? 'Verifying…' : 'Verify code'),
      ),
      const SizedBox(height: 8),
      OutlinedButton(
        onPressed: submitting
            ? null
            : () {
                _code.clear();
                auth.cancelMfa();
              },
        child: const Text('Back'),
      ),
    ];
  }

  void _submitCredentials(AuthState auth) {
    final email = _email.text.trim();
    final password = _password.text;
    if (email.isEmpty || password.isEmpty) return;
    auth.login(email, password);
  }

  void _submitCode(AuthState auth) {
    final code = _code.text.trim();
    if (code.isEmpty) return;
    auth.submitMfa(code);
  }
}
