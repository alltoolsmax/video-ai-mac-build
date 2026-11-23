<?php
declare(strict_types=1);

// Thư viện dùng chung. Nằm ngoài thư mục công khai (không có địa chỉ web nào trỏ tới).

const KEY_DOMAIN = 'VoiceAI-MrHuynh-license-v1';
const KEY_PREFIX = 'MH1-';

function private_dir(): string
{
    return getenv('ACTIVE_PRIVATE') ?: __DIR__;
}

function cfg(): array
{
    static $c = null;
    if ($c === null) {
        $f = private_dir() . '/config.php';
        if (!is_file($f)) {
            throw new RuntimeException('Thiếu config.php');
        }
        $c = require $f;
        date_default_timezone_set($c['timezone'] ?? 'Asia/Ho_Chi_Minh');
        // Cho phép sửa bảng giá từ trang admin: nếu có voice_plans.json thì đè name/days/price
        // lên giá mặc định (giữ nguyên 'type'). Không có file này thì dùng y như config.php cũ.
        $ovRaw = @file_get_contents(private_dir() . '/voice_plans.json');
        if ($ovRaw !== false && isset($c['plans']) && is_array($c['plans'])) {
            $ov = json_decode($ovRaw, true);
            if (is_array($ov)) {
                foreach ($ov as $code => $p) {
                    if (isset($c['plans'][$code]) && is_array($p)) {
                        if (isset($p['name'])) {
                            $c['plans'][$code]['name'] = (string)$p['name'];
                        }
                        if (array_key_exists('days', $p)) {
                            $c['plans'][$code]['days'] = ((int)$p['days']) ?: null;
                        }
                        if (isset($p['price'])) {
                            $c['plans'][$code]['price'] = (int)$p['price'];
                        }
                    }
                }
            }
        }
    }
    return $c;
}

function log_line(string $msg): void
{
    $dir = private_dir() . '/logs';
    if (!is_dir($dir)) {
        @mkdir($dir, 0700, true);
    }
    @file_put_contents($dir . '/server.log', '[' . date('Y-m-d H:i:s') . '] ' . $msg . "\n", FILE_APPEND | LOCK_EX);
}

function db(): PDO
{
    static $pdo = null;
    if ($pdo) {
        return $pdo;
    }
    $dir = private_dir() . '/data';
    if (!is_dir($dir)) {
        @mkdir($dir, 0700, true);
    }
    $pdo = new PDO('sqlite:' . $dir . '/orders.sqlite');
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
    $pdo->exec('PRAGMA journal_mode=WAL');
    $pdo->exec('PRAGMA busy_timeout=8000');
    $pdo->exec('CREATE TABLE IF NOT EXISTS orders (
        code TEXT PRIMARY KEY, machine_id TEXT NOT NULL, plan TEXT NOT NULL, amount INTEGER NOT NULL,
        status TEXT NOT NULL, key TEXT, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
        paid_at INTEGER, sepay_id TEXT, paid_amount INTEGER, note TEXT)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS transactions (
        sepay_id TEXT PRIMARY KEY, code TEXT, amount INTEGER, content TEXT, result TEXT, created_at INTEGER NOT NULL)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS rate (ip TEXT NOT NULL, ts INTEGER NOT NULL)');
    $pdo->exec('CREATE INDEX IF NOT EXISTS rate_ip ON rate(ip, ts)');
    return $pdo;
}

function json_out($data, int $status = 200): never
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    header('X-Content-Type-Options: nosniff');
    echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function fail(string $msg, int $status = 400): never
{
    json_out(['error' => $msg], $status);
}

// ---------------------------------------------------------------- Telegram

function telegram(string $text): bool
{
    $c = cfg();
    $token = trim((string)($c['telegram_token'] ?? ''));
    $chat = trim((string)($c['telegram_chat_id'] ?? ''));
    if ($token === '' || $chat === '' || !function_exists('curl_init')) {
        return false;
    }
    $ch = curl_init('https://api.telegram.org/bot' . $token . '/sendMessage');
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => ['chat_id' => $chat, 'text' => $text],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 8,
        CURLOPT_CONNECTTIMEOUT => 5,
    ]);
    $res = curl_exec($ch);
    $code = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    if ($res === false || $code !== 200) {
        log_line("Telegram lỗi (HTTP $code)");
        return false;
    }
    return true;
}

// ---------------------------------------------------------------- Mã máy, key

function parse_machine(string $text): ?string
{
    $t = strtoupper(trim($text));
    if (!preg_match('/^MH-([0-9A-F]{4})-([0-9A-F]{4})-([0-9A-F]{4})-([0-9A-F]{4})$/', $t, $m)) {
        return null;
    }
    return $m[1] . $m[2] . $m[3] . $m[4];   // 16 ký tự hex = 8 byte
}

function b32(string $bin): string
{
    $alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
    $bits = '';
    foreach (str_split($bin) as $ch) {
        $bits .= str_pad(decbin(ord($ch)), 8, '0', STR_PAD_LEFT);
    }
    $out = '';
    foreach (str_split($bits, 5) as $chunk) {
        $out .= $alphabet[bindec(str_pad($chunk, 5, '0', STR_PAD_RIGHT))];
    }
    return $out;
}

/** Tạo key giống hệt định dạng của app: payload 12 byte + chữ ký Ed25519 64 byte. */
function make_key(int $type, string $machineHex, ?int $issuedTs = null): string
{
    $seed = hex2bin(trim((string)cfg()['seed_hex']));
    if ($seed === false || strlen($seed) !== SODIUM_CRYPTO_SIGN_SEEDBYTES) {
        throw new RuntimeException('seed_hex không hợp lệ (cần 64 ký tự hex)');
    }
    $kp = sodium_crypto_sign_seed_keypair($seed);
    $sk = sodium_crypto_sign_secretkey($kp);
    $epoch = new DateTimeImmutable('2024-01-01', new DateTimeZone('UTC'));
    $issued = (new DateTimeImmutable('@' . ($issuedTs ?? time())))->setTimezone(new DateTimeZone(date_default_timezone_get()));
    $days = (int)$epoch->diff(new DateTimeImmutable($issued->format('Y-m-d'), new DateTimeZone('UTC')))->format('%r%a');
    $payload = chr(1) . chr($type) . hex2bin($machineHex) . pack('n', $days);
    $sig = sodium_crypto_sign_detached(KEY_DOMAIN . $payload, $sk);
    $raw = b32($payload . $sig);
    return KEY_PREFIX . implode('-', str_split($raw, 6));
}

// ---------------------------------------------------------------- VietQR (EMVCo)

function tlv(string $id, string $value): string
{
    return $id . str_pad((string)strlen($value), 2, '0', STR_PAD_LEFT) . $value;
}

function crc16(string $s): string
{
    $crc = 0xFFFF;
    for ($i = 0, $n = strlen($s); $i < $n; $i++) {
        $crc ^= ord($s[$i]) << 8;
        for ($b = 0; $b < 8; $b++) {
            $crc = ($crc & 0x8000) ? (($crc << 1) ^ 0x1021) & 0xFFFF : ($crc << 1) & 0xFFFF;
        }
    }
    return strtoupper(str_pad(dechex($crc), 4, '0', STR_PAD_LEFT));
}

/** Chuỗi nội dung mã QR chuyển khoản nhanh 24/7 (VietQR) cho đúng số tiền và nội dung. */
function vietqr(string $bin, string $account, int $amount, string $memo): string
{
    $merchant = tlv('00', 'A000000727')
        . tlv('01', tlv('00', $bin) . tlv('01', $account))
        . tlv('02', 'QRIBFTTA');
    $s = tlv('00', '01') . tlv('01', '12') . tlv('38', $merchant) . tlv('53', '704')
        . tlv('54', (string)$amount) . tlv('58', 'VN') . tlv('62', tlv('08', $memo));
    $s .= '6304';
    return $s . crc16($s);
}

// ---------------------------------------------------------------- Đơn hàng

function order_code(): string
{
    $chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
    $s = '';
    for ($i = 0; $i < 8; $i++) {
        $s .= $chars[random_int(0, strlen($chars) - 1)];
    }
    return strtoupper((string)(cfg()['code_prefix'] ?? 'VAI')) . $s;
}

function order_public(array $o, bool $withKey): array
{
    $c = cfg();
    $status = $o['status'];
    if ($status === 'pending' && (int)$o['expires_at'] < time()) {
        $status = 'expired';
    }
    $plan = $c['plans'][$o['plan']] ?? ['name' => $o['plan']];
    $out = [
        'code' => $o['code'],
        'status' => $status,
        'plan' => $o['plan'],
        'plan_name' => $plan['name'],
        'amount' => (int)$o['amount'],
        'content' => $o['code'],
        'expires_at' => (int)$o['expires_at'],
        'bank' => [
            'name' => $c['bank']['name'],
            'account' => $c['bank']['account'],
            'holder' => $c['bank']['holder'],
        ],
        'qr_payload' => vietqr($c['bank']['bin'], $c['bank']['account'], (int)$o['amount'], $o['code']),
    ];
    if ($withKey && $status === 'paid') {
        $out['key'] = $o['key'];
    }
    return $out;
}

/** Ghi nhận thanh toán: tạo key và đánh dấu đơn. Gọi trong transaction. */
function fulfil_order(array $o, int $paid, string $sepayId, string $note = ''): string
{
    $plan = cfg()['plans'][$o['plan']];
    $key = make_key((int)$plan['type'], (string)parse_machine($o['machine_id']));
    $st = db()->prepare('UPDATE orders SET status="paid", key=?, paid_at=?, sepay_id=?, paid_amount=?, note=? WHERE code=?');
    $st->execute([$key, time(), $sepayId, $paid, $note, $o['code']]);
    return $key;
}

function money(int $v): string
{
    return number_format($v, 0, ',', '.') . 'đ';
}
