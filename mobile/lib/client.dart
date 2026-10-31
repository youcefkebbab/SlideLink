import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';
import 'package:cryptography/cryptography.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

const svcUuid = '7d1c0001-5a1d-4e0b-9c3a-51d3e11a0001';
const rxUuid = '7d1c0002-5a1d-4e0b-9c3a-51d3e11a0001';
const txUuid = '7d1c0003-5a1d-4e0b-9c3a-51d3e11a0001';
const chunkSize = 100;

enum Phase { idle, scanning, connecting, needPin, connected, error }

class SlideLinkClient extends ChangeNotifier {
  Phase phase = Phase.idle;
  String? error;
  String? computerName;
  List<ScanResult> found = [];
  Map<String, dynamic> st = {'mode': 'none'};
  int? pingMs;

  final _store = const FlutterSecureStorage();
  BluetoothDevice? _dev;
  BluetoothCharacteristic? _rx, _tx;
  StreamSubscription? _notifySub, _connSub, _scanSub;
  final _buf = BytesBuilder();
  late String _deviceId;
  Uint8List? _secret;
  SimpleKeyPair? _kp;
  Uint8List _pkC = Uint8List(0);
  String? _pendingPin;
  SecretKey? _sendKey, _recvKey;
  int _seq = 0, _lastIn = 0;
  bool _userDisconnect = false, _reconnecting = false;
  final _aes = AesGcm.with256bits();
  DateTime? _pingStart;

  // ---------- storage ----------
  Future<void> init() async {
    _deviceId = await _store.read(key: 'deviceId') ??
        (() {
          final r = Random.secure();
          return List.generate(8, (_) => r.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
        })();
    await _store.write(key: 'deviceId', value: _deviceId);
    final s = await _store.read(key: 'secret');
    if (s != null) _secret = base64Decode(s);
    final last = await _store.read(key: 'lastRemoteId');
    if (last != null && _secret != null) {
      computerName = await _store.read(key: 'lastName');
      connectTo(BluetoothDevice.fromId(last), name: computerName);
    }
  }

  void clearError() {
    error = null;
    notifyListeners();
  }

  // ---------- scanning ----------
  Future<void> scan() async {
    found = [];
    error = null;
    phase = Phase.scanning;
    notifyListeners();
    try {
      await _scanSub?.cancel();
      _scanSub = FlutterBluePlus.scanResults.listen((r) {
        found = r.where((x) => x.advertisementData.serviceUuids.contains(Guid(svcUuid)) ||
            x.device.platformName.startsWith('SlideLink')).toList();
        notifyListeners();
      });
      await FlutterBluePlus.startScan(withServices: [Guid(svcUuid)], timeout: const Duration(seconds: 10));
      await FlutterBluePlus.isScanning.where((s) => s == false).first;
    } catch (e) {
      _fail('Bluetooth scan failed. Is Bluetooth turned on and permission granted?\n($e)');
      return;
    }
    if (phase == Phase.scanning) {
      phase = Phase.idle;
      notifyListeners();
    }
  }

  // ---------- connection ----------
  Future<void> connectTo(BluetoothDevice d, {String? name}) async {
    _userDisconnect = false;
    phase = Phase.connecting;
    computerName = name ?? (d.platformName.isNotEmpty ? d.platformName : 'Computer');
    error = null;
    notifyListeners();
    try {
      await FlutterBluePlus.stopScan();
      _dev = d;
      await d.connect(timeout: const Duration(seconds: 12));
      if (Platform.isAndroid) await d.requestMtu(247);
      final svcs = await d.discoverServices();
      final s = svcs.firstWhere((x) => x.uuid == Guid(svcUuid));
      _rx = s.characteristics.firstWhere((c) => c.characteristicUuid == Guid(rxUuid));
      _tx = s.characteristics.firstWhere((c) => c.characteristicUuid == Guid(txUuid));
      await _tx!.setNotifyValue(true);
      await _notifySub?.cancel();
      _notifySub = _tx!.onValueReceived.listen(_onChunk);
      await _connSub?.cancel();
      _connSub = d.connectionState.listen((cs) {
        if (cs == BluetoothConnectionState.disconnected && phase != Phase.idle) _onLost();
      });
      await _store.write(key: 'lastRemoteId', value: d.remoteId.str);
      await _store.write(key: 'lastName', value: computerName);
      await _handshake(_secret, null);
    } catch (e) {
      _fail('Could not connect to the computer. Make sure SlideLink Desktop is running and Bluetooth is on.\n($e)');
    }
  }

  void submitPin(String pin) {
    _pendingPin = pin.replaceAll(' ', '');
    phase = Phase.connecting;
    notifyListeners();
    _handshake(null, _pendingPin);
  }

  Future<void> disconnect() async {
    _userDisconnect = true;
    try { await _send({'t': 'bye'}, enc: true); } catch (_) {}
    await _store.delete(key: 'lastRemoteId');
    await _dev?.disconnect();
    phase = Phase.idle;
    st = {'mode': 'none'};
    notifyListeners();
  }

  void _onLost() async {
    if (_userDisconnect || _reconnecting || _dev == null) return;
    _reconnecting = true;
    phase = Phase.connecting;
    error = 'Connection lost – reconnecting…';
    notifyListeners();
    for (var i = 0; i < 6 && !_userDisconnect; i++) {
      await Future.delayed(const Duration(seconds: 2));
      try {
        _reconnecting = false;
        await connectTo(_dev!, name: computerName);
        if (phase == Phase.connected || phase == Phase.needPin) return;
      } catch (_) {}
      _reconnecting = true;
    }
    _reconnecting = false;
    if (phase != Phase.connected) _fail('Connection lost. Tap the computer to reconnect.');
  }

  void _fail(String m) {
    phase = Phase.error;
    error = m;
    notifyListeners();
  }

  // ---------- crypto ----------
  Future<Uint8List> _mac(Uint8List secret, String label, List<Uint8List> parts) async {
    final data = BytesBuilder()..add(utf8.encode(label));
    for (final p in parts) data.add(p);
    final m = await Hmac.sha256().calculateMac(data.toBytes(), secretKey: SecretKey(secret));
    return Uint8List.fromList(m.bytes);
  }

  Future<void> _handshake(Uint8List? secret, String? pin) async {
    final Uint8List key;
    if (pin != null) {
      final k = await Pbkdf2(macAlgorithm: Hmac.sha256(), iterations: 100000, bits: 256)
          .deriveKey(secretKey: SecretKey(utf8.encode(pin)), nonce: utf8.encode('slidelink-pin-v1'));
      key = Uint8List.fromList(await k.extractBytes());
    } else if (secret != null) {
      key = secret;
    } else {
      phase = Phase.needPin;
      notifyListeners();
      return;
    }
    _hsSecret = key;
    _kp = await X25519().newKeyPair();
    _pkC = Uint8List.fromList((await _kp!.extractPublicKey()).bytes);
    final auth = await _mac(key, 'C', [_pkC]);
    await _sendRaw(utf8.encode(jsonEncode({
      't': 'hello', 'id': _deviceId, 'name': Platform.isIOS ? 'iPhone' : 'Android phone',
      'pk': base64Encode(_pkC), 'auth': base64Encode(auth),
    })));
  }

  Uint8List? _hsSecret;

  Future<void> _finishHandshake(Map m) async {
    final pkS = Uint8List.fromList(base64Decode(m['pk']));
    final expect = await _mac(_hsSecret!, 'S', [pkS, _pkC]);
    if (!listEquals(expect, base64Decode(m['auth']))) {
      _fail('The computer could not be verified. Try pairing again.');
      return;
    }
    final shared = await X25519().sharedSecretKey(
        keyPair: _kp!, remotePublicKey: SimplePublicKey(pkS, type: KeyPairType.x25519));
    final ikm = Uint8List.fromList([...await shared.extractBytes(), ..._hsSecret!]);
    final okm = await Hkdf(hmac: Hmac.sha256(), outputLength: 64).deriveKey(
        secretKey: SecretKey(ikm), nonce: [..._pkC, ...pkS], info: utf8.encode('slidelink-v1'));
    final b = await okm.extractBytes();
    _sendKey = SecretKey(b.sublist(0, 32));
    _recvKey = SecretKey(b.sublist(32));
    _seq = 0;
    _lastIn = 0;
    phase = Phase.connected;
    error = null;
    notifyListeners();
  }

  // ---------- messaging ----------
  Future<void> _sendRaw(List<int> data) async {
    for (var i = 0; i < data.length || i == 0; i += chunkSize) {
      final end = min(i + chunkSize, data.length);
      final last = end >= data.length;
      await _rx!.write([last ? 1 : 0, ...data.sublist(i, end)], withoutResponse: false);
    }
  }

  Future<void> _send(Map<String, dynamic> msg, {bool enc = true}) async {
    if (_sendKey == null || _rx == null) return;
    _seq++;
    final body = utf8.encode(jsonEncode({...msg, 'q': _seq}));
    final box = await _aes.encrypt(body, secretKey: _sendKey!, aad: utf8.encode('SL1'));
    await _sendRaw([1, ...box.concatenation()]);
  }

  void _onChunk(List<int> c) async {
    if (c.isEmpty) return;
    _buf.add(c.sublist(1));
    if (c[0] != 1) return;
    final raw = _buf.takeBytes();
    try {
      if (raw[0] == 1) {
        final box = SecretBox.fromConcatenation(raw.sublist(1), nonceLength: 12, macLength: 16);
        final m = jsonDecode(utf8.decode(await _aes.decrypt(box, secretKey: _recvKey!, aad: utf8.encode('SL1'))));
        if ((m['q'] as int) <= _lastIn) return;
        _lastIn = m['q'];
        await _onMessage(m);
      } else {
        final m = jsonDecode(utf8.decode(raw));
        if (m['t'] == 'hello') {
          await _finishHandshake(m);
        } else if (m['t'] == 'err') {
          final code = m['code'];
          if (code == 'reauth') {
            await _handshake(_secret, null);
          } else {
            error = code == 'bad_pin' ? 'Wrong code. Check the code on the computer.' : null;
            phase = Phase.needPin;
            notifyListeners();
          }
        }
      }
    } catch (e) {
      debugPrint('rx error $e');
    }
  }

  Future<void> _onMessage(Map m) async {
    switch (m['t']) {
      case 'paired':
        _secret = Uint8List.fromList(base64Decode(m['secret']));
        await _store.write(key: 'secret', value: m['secret']);
        break;
      case 'state':
        st = Map<String, dynamic>.from(m);
        notifyListeners();
        break;
      case 'pong':
        pingMs = DateTime.now().difference(_pingStart!).inMilliseconds;
        notifyListeners();
        break;
      case 'err':
        error = {
          'no_vlc': 'VLC is not running. On the computer press “Open MP4 video”.',
          'no_pdf': 'No presentation is open on the computer.',
          'keys_failed': 'The computer blocked keyboard control (see Troubleshooting).',
        }[m['code']] ?? 'Command failed.';
        notifyListeners();
        break;
    }
  }

  void cmd(String a, [Map<String, dynamic> extra = const {}]) {
    _send({'t': 'cmd', 'a': a, ...extra});
  }

  Future<int?> testConnection() async {
    pingMs = null;
    _pingStart = DateTime.now();
    await _send({'t': 'ping', 'id': 1});
    for (var i = 0; i < 30 && pingMs == null; i++) {
      await Future.delayed(const Duration(milliseconds: 100));
    }
    return pingMs;
  }
}
