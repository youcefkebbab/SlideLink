import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'client.dart';

void main() => runApp(const SlideLinkApp());

class SlideLinkApp extends StatefulWidget {
  const SlideLinkApp({super.key});
  @override
  State<SlideLinkApp> createState() => _AppState();
}

class _AppState extends State<SlideLinkApp> {
  ThemeMode mode = ThemeMode.system;
  final client = SlideLinkClient();

  @override
  void initState() {
    super.initState();
    client.init();
  }

  ThemeData _theme(Brightness b) => ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF4F6BFF), brightness: b));

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'SlideLink',
        debugShowCheckedModeBanner: false,
        theme: _theme(Brightness.light),
        darkTheme: _theme(Brightness.dark),
        themeMode: mode,
        home: Home(client: client, toggleTheme: () => setState(() {
              mode = Theme.of(context).brightness == Brightness.dark ? ThemeMode.light : ThemeMode.dark;
            })),
      );
}

class Home extends StatelessWidget {
  final SlideLinkClient client;
  final VoidCallback toggleTheme;
  const Home({super.key, required this.client, required this.toggleTheme});

  @override
  Widget build(BuildContext context) => ListenableBuilder(
      listenable: client,
      builder: (context, _) {
        final connected = client.phase == Phase.connected;
        return Scaffold(
          appBar: AppBar(
            title: Text(connected ? client.computerName ?? 'Connected' : 'SlideLink'),
            actions: [
              IconButton(icon: const Icon(Icons.brightness_6), onPressed: toggleTheme),
              IconButton(icon: const Icon(Icons.help_outline), onPressed: () => troubleshoot(context)),
              if (connected)
                IconButton(icon: const Icon(Icons.link_off), onPressed: client.disconnect),
            ],
          ),
          body: SafeArea(
            child: connected ? Remote(client: client) : ConnectScreen(client: client),
          ),
        );
      });
}

void troubleshoot(BuildContext c) => showDialog(
    context: c,
    builder: (_) => AlertDialog(
          title: const Text('Troubleshooting'),
          content: const SingleChildScrollView(
              child: Text('1. Open SlideLink Desktop on the computer – it must say “Ready”.\n\n'
                  '2. Turn Bluetooth ON on both devices and allow the Bluetooth permission on the phone.\n\n'
                  '3. Stay within ~5 m of the computer.\n\n'
                  '4. Computer not listed? Close and reopen SlideLink Desktop, then tap Scan again.\n\n'
                  '5. Wrong code? Use the code currently shown on the computer (tap “New pairing code”).\n\n'
                  '6. Ubuntu: use the “Ubuntu on Xorg” login session if keys do not work in other apps.\n\n'
                  '7. Use the Test Connection button to check the link.')),
          actions: [TextButton(onPressed: () => Navigator.pop(c), child: const Text('OK'))],
        ));

// ------------------------------------------------------------------ connect
class ConnectScreen extends StatefulWidget {
  final SlideLinkClient client;
  const ConnectScreen({super.key, required this.client});
  @override
  State<ConnectScreen> createState() => _ConnectState();
}

class _ConnectState extends State<ConnectScreen> {
  final pin = TextEditingController();
  SlideLinkClient get c => widget.client;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (c.phase == Phase.idle) c.scan();
    });
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    if (c.phase == Phase.needPin) {
      return Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          Icon(Icons.lock_outline, size: 56, color: cs.primary),
          const SizedBox(height: 16),
          Text('Enter the code shown on ${c.computerName ?? "your computer"}',
              textAlign: TextAlign.center, style: Theme.of(context).textTheme.titleMedium),
          if (c.error != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(c.error!, style: TextStyle(color: cs.error))),
          const SizedBox(height: 16),
          TextField(
              controller: pin,
              autofocus: true,
              keyboardType: TextInputType.number,
              maxLength: 7,
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 32, letterSpacing: 6),
              inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9 ]'))]),
          FilledButton(onPressed: () => c.submitPin(pin.text), child: const Text('Connect')),
        ]),
      );
    }
    return Padding(
      padding: const EdgeInsets.all(20),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text('Your computers', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 4),
        Text(c.phase == Phase.scanning ? 'Searching via Bluetooth…' : 'Open SlideLink Desktop, then pick it below.',
            style: TextStyle(color: cs.onSurfaceVariant)),
        if (c.phase == Phase.scanning || c.phase == Phase.connecting) const Padding(padding: EdgeInsets.symmetric(vertical: 8), child: LinearProgressIndicator()),
        if (c.error != null)
          Card(color: cs.errorContainer, child: Padding(padding: const EdgeInsets.all(12), child: Text(c.error!, style: TextStyle(color: cs.onErrorContainer)))),
        Expanded(
          child: c.found.isEmpty
              ? Center(child: Icon(Icons.bluetooth_searching, size: 72, color: cs.outline))
              : ListView(children: [
                  for (final r in c.found)
                    Card(
                        child: ListTile(
                      leading: const Icon(Icons.computer),
                      title: Text(r.device.platformName.isEmpty ? 'SlideLink computer' : r.device.platformName),
                      subtitle: Text('Signal ${r.rssi} dBm'),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => c.connectTo(r.device, name: r.device.platformName),
                    ))
                ]),
        ),
        FilledButton.icon(onPressed: c.phase == Phase.scanning ? null : c.scan, icon: const Icon(Icons.refresh), label: const Text('Scan again')),
      ]),
    );
  }
}

// ------------------------------------------------------------------ remote
class Remote extends StatefulWidget {
  final SlideLinkClient client;
  const Remote({super.key, required this.client});
  @override
  State<Remote> createState() => _RemoteState();
}

class _RemoteState extends State<Remote> {
  SlideLinkClient get c => widget.client;
  DateTime? started;
  Timer? tick;

  @override
  void initState() {
    super.initState();
    tick = Timer.periodic(const Duration(seconds: 1), (_) => mounted ? setState(() {}) : null);
  }

  @override
  void dispose() {
    tick?.cancel();
    super.dispose();
  }

  String fmt(num s) {
    final d = Duration(seconds: s.toInt());
    String two(int n) => n.toString().padLeft(2, '0');
    return d.inHours > 0 ? '${d.inHours}:${two(d.inMinutes % 60)}:${two(d.inSeconds % 60)}' : '${two(d.inMinutes)}:${two(d.inSeconds % 60)}';
  }

  void haptic() => HapticFeedback.lightImpact();
  void send(String a, [Map<String, dynamic> x = const {}]) {
    haptic();
    c.cmd(a, x);
  }

  @override
  Widget build(BuildContext context) {
    final mode = c.st['mode'];
    return Column(children: [
      if (c.error != null)
        MaterialBanner(content: Text(c.error!), actions: [TextButton(onPressed: c.clearError, child: const Text('OK'))]),
      Expanded(child: mode == 'video' ? video(context) : pdf(context, mode == 'pdf')),
      Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: TextButton.icon(
            onPressed: () async {
              final ms = await c.testConnection();
              if (!context.mounted) return;
              ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(ms == null ? 'No reply – connection problem' : 'Connection OK • $ms ms')));
            },
            icon: const Icon(Icons.network_check),
            label: const Text('Test Connection')),
      ),
    ]);
  }

  Widget big(IconData i, String a, {double size = 40, Map<String, dynamic> x = const {}, bool filled = false}) {
    final b = filled
        ? FilledButton(onPressed: () => send(a, x), style: FilledButton.styleFrom(shape: const CircleBorder()), child: Icon(i, size: size))
        : FilledButton.tonal(onPressed: () => send(a, x), style: FilledButton.styleFrom(shape: const CircleBorder()), child: Icon(i, size: size));
    return b;
  }

  // ---------------- PDF
  bool laser = false;
  double? dragLaser;
  int lastLaserSent = 0;
  Widget laserSettings(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final size = (dragLaser ?? ((c.st['ls'] ?? 14) as int).toDouble());
    void sendSize(double v) => c.cmd('laser_size', {'v': v.round()});
    return Column(children: [
      Row(children: [
        const Text('Thin'),
        Expanded(
            child: Slider(
                min: 4,
                max: 60,
                divisions: 56,
                value: size.clamp(4, 60).toDouble(),
                onChanged: (v) {
                  setState(() => dragLaser = v);
                  final now = DateTime.now().millisecondsSinceEpoch;
                  if (now - lastLaserSent > 80) { lastLaserSent = now; sendSize(v); }
                },
                onChangeEnd: (v) { sendSize(v); setState(() => dragLaser = null); })),
        const Text('Thick'),
      ]),
      Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Container(width: 6 + size * 0.6, height: 6 + size * 0.6, decoration: BoxDecoration(color: const Color(0xFFFF2A2A), shape: BoxShape.circle, boxShadow: const [BoxShadow(color: Color(0x80FF2A2A), blurRadius: 8, spreadRadius: 2)])),
        Text('Thickness ${size.round()}', style: Theme.of(context).textTheme.titleMedium),
        TextButton(onPressed: () { setState(() => dragLaser = null); c.cmd('laser_reset'); }, child: const Text('Reset')),
      ]),
      if (c.st['le'] == false)
        Row(mainAxisAlignment: MainAxisAlignment.center, children: [
          Text('Laser is turned off on the computer', style: TextStyle(color: cs.error)),
          TextButton(onPressed: () => c.cmd('laser_enable', {'on': true}), child: const Text('Turn on')),
        ]),
    ]);
  }

  Widget pdf(BuildContext context, bool builtIn) {
    final pg = (c.st['pg'] ?? 0) as int, n = (c.st['n'] ?? 0) as int;
    final cs = Theme.of(context).colorScheme;
    final elapsed = started == null ? 0 : DateTime.now().difference(started!).inSeconds;
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(children: [
        Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          GestureDetector(onTap: () => setState(() => started = null), child: Chip(avatar: const Icon(Icons.timer, size: 18), label: Text(started == null ? '00:00' : fmt(elapsed)))),
          Text(builtIn ? '$pg / $n' : 'External viewer', style: Theme.of(context).textTheme.headlineMedium),
          IconButton(icon: const Icon(Icons.pin_outlined), onPressed: builtIn ? () => goTo(context, n) : null),
        ]),
        if (builtIn) LinearProgressIndicator(value: n == 0 ? 0 : pg / n, minHeight: 8, borderRadius: BorderRadius.circular(8)),
        if (!builtIn)
          Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text('No slide counter for other viewers. Use “Open PDF” on the computer for page numbers, go-to-page and laser.',
                  textAlign: TextAlign.center, style: TextStyle(color: cs.onSurfaceVariant))),
        Expanded(
          child: laser && builtIn
              ? Column(children: [Expanded(child: LayoutBuilder(builder: (ctx, box) => GestureDetector(
                    onPanUpdate: (d) => c.cmd('laser', {'x': (d.localPosition.dx / box.maxWidth).clamp(0, 1), 'y': (d.localPosition.dy / box.maxHeight).clamp(0, 1), 'on': true}),
                    onPanEnd: (_) => c.cmd('laser', {'on': false}),
                    child: Container(margin: const EdgeInsets.symmetric(vertical: 12), decoration: BoxDecoration(color: cs.surfaceContainerHighest, borderRadius: BorderRadius.circular(24)), child: const Center(child: Text('Drag to move the laser pointer'))),
                  ))), laserSettings(context)])
              : Row(children: [
                  Expanded(child: SizedBox.expand(child: Padding(padding: const EdgeInsets.all(6), child: FilledButton.tonal(onPressed: () => send('prev'), style: FilledButton.styleFrom(shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(28))), child: const Column(mainAxisAlignment: MainAxisAlignment.center, children: [Icon(Icons.arrow_back_ios_new, size: 44), Text('Previous')]))))),
                  Expanded(flex: 2, child: SizedBox.expand(child: Padding(padding: const EdgeInsets.all(6), child: FilledButton(onPressed: () { started ??= DateTime.now(); send('next'); }, style: FilledButton.styleFrom(shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(28))), child: const Column(mainAxisAlignment: MainAxisAlignment.center, children: [Icon(Icons.arrow_forward_ios, size: 56), Text('Next', style: TextStyle(fontSize: 20))]))))),
                ]),
        ),
        Wrap(spacing: 8, alignment: WrapAlignment.center, children: [
          ActionChip(avatar: const Icon(Icons.first_page), label: const Text('First'), onPressed: () => send('first')),
          ActionChip(avatar: const Icon(Icons.last_page), label: const Text('Last'), onPressed: () => send('last')),
          ActionChip(avatar: const Icon(Icons.slideshow), label: const Text('Start'), onPressed: () { started ??= DateTime.now(); send('start'); }),
          ActionChip(avatar: const Icon(Icons.close), label: const Text('Exit'), onPressed: () => send('exit')),
          ActionChip(avatar: const Icon(Icons.fullscreen), label: const Text('Fullscreen'), onPressed: () => send('fullscreen')),
          FilterChip(avatar: const Icon(Icons.circle), label: const Text('Black'), selected: c.st['scr'] == 'b', onSelected: (_) => send('black')),
          FilterChip(avatar: const Icon(Icons.circle_outlined), label: const Text('White'), selected: c.st['scr'] == 'w', onSelected: (_) => send('white')),
          if (builtIn) FilterChip(avatar: const Icon(Icons.adjust), label: const Text('Laser'), selected: laser, onSelected: (v) { setState(() => laser = v); if (!v) c.cmd('laser', {'on': false}); }),
        ]),
      ]),
    );
  }

  Future<void> goTo(BuildContext context, int n) async {
    final t = TextEditingController();
    final v = await showDialog<int>(
        context: context,
        builder: (_) => AlertDialog(
              title: Text('Go to page (1–$n)'),
              content: TextField(controller: t, autofocus: true, keyboardType: TextInputType.number),
              actions: [TextButton(onPressed: () => Navigator.pop(context, int.tryParse(t.text)), child: const Text('Go'))],
            ));
    if (v != null) send('goto', {'n': v});
  }

  // ---------------- Video
  double? dragging;
  Widget video(BuildContext context) {
    final t = (c.st['vt'] ?? 0) as int, l = (c.st['vl'] ?? 0) as int;
    final playing = c.st['vs'] == 'playing';
    final v = (c.st['vv'] ?? 0) as int;
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
        Text('${fmt(dragging != null ? dragging! * l : t)} / ${fmt(l)}', style: Theme.of(context).textTheme.headlineMedium),
        Slider(
            value: dragging ?? (l == 0 ? 0 : (t / l).clamp(0, 1).toDouble()),
            onChanged: (x) => setState(() => dragging = x),
            onChangeEnd: (x) { send('seek', {'pct': x * 100}); setState(() => dragging = null); }),
        const SizedBox(height: 12),
        Row(mainAxisAlignment: MainAxisAlignment.spaceEvenly, children: [
          big(Icons.skip_previous, 'vprev', size: 32),
          big(Icons.replay_10, 'back10', size: 36),
          SizedBox(width: 120, height: 120, child: big(playing ? Icons.pause : Icons.play_arrow, 'toggle', size: 64, filled: true)),
          big(Icons.forward_10, 'fwd10', size: 36),
          big(Icons.skip_next, 'vnext', size: 32),
        ]),
        const SizedBox(height: 28),
        Row(mainAxisAlignment: MainAxisAlignment.spaceEvenly, children: [
          IconButton.filledTonal(iconSize: 32, onPressed: () => send('voldown'), icon: const Icon(Icons.volume_down)),
          Text('$v%', style: Theme.of(context).textTheme.titleLarge),
          IconButton.filledTonal(iconSize: 32, onPressed: () => send('volup'), icon: const Icon(Icons.volume_up)),
          IconButton.filledTonal(iconSize: 32, onPressed: () => send('mute'), icon: Icon(v == 0 ? Icons.volume_off : Icons.volume_mute)),
          IconButton.filledTonal(iconSize: 32, onPressed: () => send('vfull'), icon: const Icon(Icons.fullscreen)),
          IconButton.filledTonal(iconSize: 32, onPressed: () => send('stop'), icon: const Icon(Icons.stop)),
        ]),
      ]),
    );
  }
}
