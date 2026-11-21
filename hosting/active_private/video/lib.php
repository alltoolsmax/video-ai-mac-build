<?php
declare(strict_types=1);

// Video AI - Mr. Huỳnh · thư viện máy chủ bản quyền (PHP + SQLite), chạy chung hosting với Voice AI.
// Toàn bộ nằm trong namespace VideoAI để KHÔNG trùng tên hàm với lib.php của Voice AI.
// Giấy phép = base64url(JSON) + "." + base64url(chữ ký Ed25519) — phần mềm kiểm tra bằng khóa công khai gắn sẵn.

namespace VideoAI;

use PDO;
use RuntimeException;
use Throwable;

const DAY = 86400;
const KEY_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';
const ORDER_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
const PRODUCT = 'videoai';

function dir(): string
{
    return getenv('VIDEOAI_PRIVATE') ?: __DIR__;
}

function voice_private(): string
{
    return getenv('ACTIVE_PRIVATE') ?: dirname(dir());
}

function cfg(): array
{
    static $c = null;
    if ($c === null) {
        $f = dir() . '/config.php';
        if (!is_file($f)) {
            throw new RuntimeException('Thiếu active_private/video/config.php');
        }
        $c = require $f;
        date_default_timezone_set($c['timezone'] ?? 'Asia/Ho_Chi_Minh');
    }
    return $c;
}

/** Cấu hình Voice AI (active_private/config.php) — dùng chung SePay, ngân hàng, Telegram, tiền tố mã đơn. */
function voice_cfg(): array
{
    static $v = null;
    if ($v === null) {
        $f = voice_private() . '/config.php';
        $v = is_file($f) ? (require $f) : [];
        if (!is_array($v)) {
            $v = [];
        }
    }
    return $v;
}

/** Lấy giá trị: ưu tiên config Video AI, để trống thì dùng của Voice AI. */
function opt(string $k, $default = null)
{
    $c = cfg();
    if (array_key_exists($k, $c) && $c[$k] !== '' && $c[$k] !== null) {
        return $c[$k];
    }
    $v = voice_cfg();
    return (array_key_exists($k, $v) && $v[$k] !== '' && $v[$k] !== null) ? $v[$k] : $default;
}

function now(): int
{
    return time();
}

function log_line(string $msg): void
{
    $d = dir() . '/logs';
    if (!is_dir($d)) {
        @mkdir($d, 0700, true);
    }
    @file_put_contents($d . '/videoai.log', '[' . date('Y-m-d H:i:s') . '] ' . $msg . "\n", FILE_APPEND | LOCK_EX);
}

function db(): PDO
{
    static $pdo = null;
    if ($pdo) {
        return $pdo;
    }
    $d = dir() . '/data';
    if (!is_dir($d)) {
        @mkdir($d, 0700, true);
    }
    $pdo = new PDO('sqlite:' . $d . '/videoai.sqlite');
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
    $pdo->exec('PRAGMA journal_mode=WAL');
    $pdo->exec('PRAGMA busy_timeout=8000');
    $pdo->exec('CREATE TABLE IF NOT EXISTS plans (code TEXT PRIMARY KEY, name TEXT NOT NULL, days INTEGER NOT NULL,
        price INTEGER NOT NULL, sort INTEGER NOT NULL DEFAULT 0, badge TEXT, active INTEGER NOT NULL DEFAULT 1)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS keys (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL UNIQUE,
        plan TEXT NOT NULL, days INTEGER NOT NULL, status TEXT NOT NULL DEFAULT "new", machine TEXT, activated_at INTEGER,
        expires_at INTEGER, transfers INTEGER NOT NULL DEFAULT 0, last_transfer_at INTEGER, merged_into TEXT,
        customer TEXT, note TEXT, order_code TEXT, price INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, last_check_at INTEGER)');
    $pdo->exec('CREATE INDEX IF NOT EXISTS keys_machine ON keys(machine)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS orders (code TEXT PRIMARY KEY, plan TEXT NOT NULL, amount INTEGER NOT NULL,
        machine TEXT, status TEXT NOT NULL DEFAULT "pending", key TEXT, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
        paid_at INTEGER, sepay_id TEXT, paid_amount INTEGER, note TEXT)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS transactions (sepay_id TEXT PRIMARY KEY, code TEXT, amount INTEGER, content TEXT,
        result TEXT, created_at INTEGER NOT NULL)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS guides (page TEXT PRIMARY KEY, url TEXT NOT NULL, updated_at INTEGER NOT NULL)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL, kind TEXT NOT NULL,
        product TEXT NOT NULL DEFAULT "videoai", key TEXT, machine TEXT, detail TEXT)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS releases (id INTEGER PRIMARY KEY AUTOINCREMENT, version TEXT NOT NULL, url TEXT NOT NULL,
        sha256 TEXT, size INTEGER, notes TEXT, mandatory INTEGER NOT NULL DEFAULT 0, min_version TEXT, active INTEGER NOT NULL DEFAULT 1,
        created_at INTEGER NOT NULL)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS rate (k TEXT NOT NULL, ts INTEGER NOT NULL)');
    $pdo->exec('CREATE INDEX IF NOT EXISTS rate_k ON rate(k, ts)');
    if ((int)$pdo->query('SELECT COUNT(*) FROM plans')->fetchColumn() === 0) {
        $i = 0;
        $st = $pdo->prepare('INSERT INTO plans (code, name, days, price, sort, badge) VALUES (?,?,?,?,?,?)');
        foreach ((cfg()['plans'] ?? []) as $code => $p) {
            $st->execute([$code, $p['name'], (int)$p['days'], (int)$p['price'], ++$i, $p['badge'] ?? null]);
        }
    }
    return $pdo;
}

function json_out($data, int $status = 200): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    header('X-Content-Type-Options: nosniff');
    echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function fail(string $code, string $message, int $status = 400, array $extra = []): void
{
    json_out(['ok' => false, 'code' => $code, 'message' => $message] + $extra, $status);
}

function event(string $kind, ?string $key = null, ?string $machine = null, ?string $detail = null, string $product = PRODUCT): void
{
    try {
        db()->prepare('INSERT INTO events (at, kind, product, key, machine, detail) VALUES (?,?,?,?,?,?)')
            ->execute([now(), $kind, $product, $key, $machine, $detail !== null ? mb_substr($detail, 0, 500) : null]);
    } catch (Throwable $e) {
    }
}

/** Giới hạn số lần gọi theo khóa (IP...) trong 1 phút / 1 giờ. */
function limited(string $k, int $max, int $window = 60): bool
{
    $max *= max(1, (int)(cfg()['rate_limit_scale'] ?? 1));      // chỉ tăng khi kiểm thử
    $pdo = db();
    $pdo->prepare('DELETE FROM rate WHERE ts < ?')->execute([now() - 3600]);
    $q = $pdo->prepare('SELECT COUNT(*) FROM rate WHERE k = ? AND ts > ?');
    $q->execute([$k, now() - $window]);
    if ((int)$q->fetchColumn() >= $max) {
        return true;
    }
    $pdo->prepare('INSERT INTO rate (k, ts) VALUES (?, ?)')->execute([$k, now()]);
    return false;
}

function client_ip(): string
{
    return (string)($_SERVER['REMOTE_ADDR'] ?? '?');
}

function rand_from(string $alphabet, int $n): string
{
    $s = '';
    for ($i = 0; $i < $n; $i++) {
        $s .= $alphabet[random_int(0, strlen($alphabet) - 1)];
    }
    return $s;
}

function new_key(): string
{
    return 'VAI-' . rand_from(KEY_ALPHABET, 4) . '-' . rand_from(KEY_ALPHABET, 4) . '-' . rand_from(KEY_ALPHABET, 4) . '-' . rand_from(KEY_ALPHABET, 4);
}

function mask(?string $k): string
{
    return $k ? substr($k, 0, 4) . '••••-••••-' . substr($k, -4) : '';
}

function money(int $v): string
{
    return number_format($v, 0, ',', '.') . 'đ';
}

function valid_machine($m): bool
{
    return is_string($m) && preg_match('/^[a-f0-9]{32,64}$/', $m) === 1;
}

// ---------------------------------------------------------------- chữ ký

function b64url(string $bin): string
{
    return rtrim(strtr(base64_encode($bin), '+/', '-_'), '=');
}

function secret_key(): string
{
    static $sk = null;
    if ($sk === null) {
        $seed = hex2bin(trim((string)(cfg()['seed_hex'] ?? '')));
        if ($seed === false || strlen($seed) !== SODIUM_CRYPTO_SIGN_SEEDBYTES) {
            throw new RuntimeException('seed_hex của Video AI không hợp lệ (cần 64 ký tự hex)');
        }
        $sk = sodium_crypto_sign_secretkey(sodium_crypto_sign_seed_keypair($seed));
    }
    return $sk;
}

function public_key_b64url(): string
{
    $seed = hex2bin(trim((string)(cfg()['seed_hex'] ?? '')));
    return b64url(sodium_crypto_sign_publickey(sodium_crypto_sign_seed_keypair($seed)));
}

/** Giấy phép có chữ ký cho máy $machine. */
function issue(string $machine, array $info): array
{
    $t = now();
    $payload = [
        'v' => 1, 'p' => PRODUCT, 'm' => $machine, 'iat' => $t,
        'kind' => $info['kind'], 'key' => isset($info['key']) ? mask($info['key']) : '',
        'plan' => $info['plan'], 'plan_name' => $info['plan_name'], 'exp' => (int)$info['exp'],
        'chk' => $t + (int)(cfg()['recheck_hours'] ?? 24) * 3600,
        'grace' => (int)(cfg()['offline_grace_days'] ?? 3) * DAY,
    ];
    $body = b64url(json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));
    $sig = sodium_crypto_sign_detached($body, secret_key());
    return ['token' => $body . '.' . b64url($sig), 'license' => $payload];
}

function plan(string $code): ?array
{
    $q = db()->prepare('SELECT * FROM plans WHERE code=?');
    $q->execute([$code]);
    return $q->fetch() ?: null;
}

function key_row(string $key): ?array
{
    $q = db()->prepare('SELECT * FROM keys WHERE key=?');
    $q->execute([$key]);
    return $q->fetch() ?: null;
}

function key_token(array $k): array
{
    $p = plan($k['plan']);
    return issue((string)$k['machine'], ['kind' => 'key', 'key' => $k['key'], 'plan' => $k['plan'],
        'plan_name' => $p ? $p['name'] : $k['plan'], 'exp' => (int)$k['expires_at']]);
}

function alive(?array $k): bool
{
    return $k && $k['status'] === 'active' && ((int)$k['expires_at'] === 0 || (int)$k['expires_at'] > now());
}

function active_key_on_machine(string $machine, ?string $except = null): ?array
{
    $q = db()->prepare('SELECT * FROM keys WHERE machine=? AND status="active" ORDER BY expires_at=0 DESC, expires_at DESC');
    $q->execute([$machine]);
    foreach ($q->fetchAll() as $k) {
        if ($k['key'] !== $except && alive($k)) {
            return $k;
        }
    }
    return null;
}

// ---------------------------------------------------------------- API cho phần mềm

function api_plans(): void
{
    $rows = db()->query('SELECT code, name, days, price, badge FROM plans WHERE active=1 ORDER BY sort')->fetchAll();
    foreach ($rows as &$r) {
        $r['days'] = (int)$r['days'];
        $r['price'] = (int)$r['price'];
    }
    $bank = bank();
    json_out(['ok' => true, 'plans' => $rows, 'payment' => (bool)($bank && opt('sepay_api_key')),
        'contact' => ['zalo' => opt('contact_zalo', ''), 'phone' => opt('contact_phone', ''), 'name' => opt('contact_name', '')]]);
}

function api_guides(): void
{
    $g = [];
    foreach (db()->query('SELECT page, url FROM guides')->fetchAll() as $r) {
        if ($r['url']) {
            $g[$r['page']] = $r['url'];
        }
    }
    json_out(['ok' => true, 'guides' => $g]);
}

// ------------------------------------------------------------------ cập nhật phần mềm
function valid_version(string $v): bool
{
    return (bool)preg_match('/^\d{1,4}(\.\d{1,4}){1,3}$/', $v);
}

// ---------------------------------------------------------------- bộ cài DUY NHẤT trên trang tải
// Khách tải lần đầu và phần mềm tự cập nhật đều dùng một file: https://mrhuynh.net/downloads/video_ai_mrhuynh_win.exe
const SITE_FILE = 'video_ai_mrhuynh_win.exe';

function site_installer_url(): string
{
    return (string)opt('site_installer_url', 'https://mrhuynh.net/downloads/' . SITE_FILE);
}

/** Đường dẫn file trên ổ đĩa hosting (cùng tài khoản cPanel) – null nếu PHP không đọc trực tiếp được. */
function site_installer_path(string $from): ?string
{
    $c = [];
    $o = (string)opt('site_downloads_dir', '');
    if ($o !== '') {
        $c[] = rtrim($o, '/');
    }
    $home = dirname($from, 2);                      // .../active.mrhuynh.net/admin → thư mục chứa các web
    foreach ([$home . '/public_html/downloads', $home . '/downloads', dirname($home) . '/public_html/downloads'] as $d) {
        $c[] = $d;
    }
    foreach ($c as $d) {
        $f = $d . '/' . SITE_FILE;
        if (@is_file($f) && @is_readable($f)) {
            return $f;
        }
    }
    return null;
}

/** Số phiên bản ghi trong bộ cài (ProductVersion / FileVersion của Inno Setup, chuỗi UTF-16) – '' nếu không thấy. */
function pe_product_version(string $head): string
{
    foreach (['ProductVersion', 'FileVersion'] as $k) {
        $key = mb_convert_encoding($k, 'UTF-16LE', 'UTF-8') . "\0\0";
        $p = strpos($head, $key);
        if ($p === false) {
            continue;
        }
        $rest = substr($head, $p + strlen($key), 80);
        $rest = ltrim($rest, "\0");
        if (preg_match('/^((?:[0-9.]\x00){1,40})/', $rest, $m)) {
            $v = str_replace("\0", '', $m[1]);
            $v = preg_replace('/(\.0)+$/', '', $v) ?: $v;           // 1.9.10.0 → 1.9.10
            if (preg_match('/^\d+\.\d+(\.\d+){0,2}$/', $v)) {
                return $v;
            }
        }
    }
    return '';
}

/** Đọc bộ cài (file trên ổ đĩa hoặc tải qua https) một lượt: SHA-256, dung lượng, có phải Inno Setup, phiên bản. */
function inspect_installer(string $src): array
{
    $ctx = stream_context_create(['http' => ['timeout' => 60, 'header' => "Cache-Control: no-cache\r\n",
        'user_agent' => 'VideoAI-Admin']]);
    $f = @fopen($src, 'rb', false, $ctx);
    if (!$f) {
        throw new RuntimeException('Không mở được ' . $src);
    }
    $h = hash_init('sha256');
    $size = 0;
    $head = '';
    $inno = false;
    $prev = '';
    while (!feof($f)) {
        $chunk = fread($f, 1 << 20);
        if ($chunk === false || $chunk === '') {
            if (feof($f)) {
                break;
            }
            continue;
        }
        hash_update($h, $chunk);
        $size += strlen($chunk);
        if (strlen($head) < (8 << 20)) {
            $head .= substr($chunk, 0, (8 << 20) - strlen($head));
        }
        if (!$inno && strpos($prev . $chunk, 'Inno Setup') !== false) {
            $inno = true;
        }
        $prev = substr($chunk, -16);
    }
    fclose($f);
    return ['sha256' => hash_final($h), 'size' => $size, 'inno' => $inno, 'version' => pe_product_version($head)];
}

function is_inno_setup(string $path): bool
{
    $f = @fopen($path, 'rb');
    if (!$f) {
        return false;
    }
    $prev = '';
    while (!feof($f)) {                          // bộ cài Inno Setup luôn có chuỗi "Inno Setup"
        $chunk = fread($f, 1 << 20);
        if ($chunk === false) {
            break;
        }
        if (strpos($prev . $chunk, 'Inno Setup') !== false) {
            fclose($f);
            return true;
        }
        $prev = substr($chunk, -32);
    }
    fclose($f);
    return false;
}

function latest_release(): ?array
{
    $rows = db()->query('SELECT * FROM releases WHERE active=1')->fetchAll();
    usort($rows, fn($a, $b) => version_compare($b['version'], $a['version']) ?: ((int)$b['id'] <=> (int)$a['id']));
    return $rows[0] ?? null;
}

function api_version(): void
{
    header('Cache-Control: no-store');
    $r = latest_release();
    if (!$r) {
        json_out(['ok' => true, 'version' => '0.0.0']);
    }
    json_out(['ok' => true, 'version' => $r['version'], 'url' => $r['url'], 'sha256' => (string)$r['sha256'],
        'size' => (int)$r['size'], 'notes' => (string)$r['notes'], 'mandatory' => (bool)$r['mandatory'],
        'min_version' => (string)($r['min_version'] ?? ''), 'released_at' => (int)$r['created_at']]);
}

function api_activate(array $b): void
{
    $machine = $b['machine'];
    $code = strtoupper(preg_replace('/\s+/', '', (string)($b['key'] ?? '')));
    $pdo = db();
    $k = key_row($code);
    if (!$k) {
        event('bad_key', substr($code, 0, 40), $machine);
        fail('bad_key', 'Key không đúng. Kiểm tra lại từng ký tự.', 404);
    }
    if ($k['status'] === 'revoked') {
        fail('revoked', 'Key đã bị khóa. Liên hệ người bán.', 403);
    }
    if ($k['status'] === 'merged') {
        if ($k['merged_into']) {
            $main = key_row($k['merged_into']);
            if ($main && $main['machine'] === $machine && alive($main)) {
                json_out(['ok' => true, 'full_key' => $main['key']] + key_token($main));
            }
        }
        fail('used', 'Key này đã được dùng để gia hạn.', 409);
    }
    if ($k['status'] === 'new') {
        $cur = active_key_on_machine($machine, $k['key']);
        if ($cur) {   // gia hạn cộng dồn vào key đang dùng trên máy này
            if ((int)$cur['expires_at'] === 0) {
                fail('already_lifetime', 'Máy này đã có bản quyền vĩnh viễn, không cần gia hạn.', 409);
            }
            $exp = (int)$k['days'] === 0 ? 0 : max((int)$cur['expires_at'], now()) + (int)$k['days'] * DAY;
            $pdo->beginTransaction();
            $pdo->prepare('UPDATE keys SET expires_at=? WHERE id=?')->execute([$exp, $cur['id']]);
            $pdo->prepare('UPDATE keys SET status="merged", merged_into=?, machine=?, activated_at=? WHERE id=?')
                ->execute([$cur['key'], $machine, now(), $k['id']]);
            $pdo->commit();
            event('renew', $k['key'], $machine, '+' . $k['days'] . ' ngày vào ' . $cur['key']);
            $main = key_row($cur['key']);
            json_out(['ok' => true, 'renewed' => true, 'added_days' => (int)$k['days'], 'full_key' => $main['key']] + key_token($main));
        }
        $exp = (int)$k['days'] === 0 ? 0 : now() + (int)$k['days'] * DAY;
        $pdo->prepare('UPDATE keys SET status="active", machine=?, activated_at=?, expires_at=? WHERE id=?')
            ->execute([$machine, now(), $exp, $k['id']]);
        event('activate', $k['key'], $machine);
        $k = key_row($code);
        json_out(['ok' => true, 'full_key' => $k['key']] + key_token($k));
    }
    if ((int)$k['expires_at'] !== 0 && (int)$k['expires_at'] <= now()) {
        fail('expired', 'Key đã hết hạn. Nhập key mới để gia hạn.', 403);
    }
    if ($k['machine'] !== $machine) {
        $cdDays = (int)(cfg()['transfer_cooldown_days'] ?? 30);
        $cd = $cdDays * DAY;
        if ($k['last_transfer_at'] && now() - (int)$k['last_transfer_at'] < $cd) {
            $left = (int)ceil(((int)$k['last_transfer_at'] + $cd - now()) / DAY);
            fail('transfer_cooldown', "Key đang dùng trên máy khác. Bạn chỉ được tự chuyển máy 1 lần mỗi $cdDays ngày (còn $left ngày). Liên hệ người bán để được hỗ trợ.", 409);
        }
        $pdo->prepare('UPDATE keys SET machine=?, transfers=transfers+1, last_transfer_at=? WHERE id=?')
            ->execute([$machine, now(), $k['id']]);
        event('transfer', $k['key'], $machine, 'từ ' . $k['machine']);
    }
    $k = key_row($code);
    json_out(['ok' => true, 'full_key' => $k['key']] + key_token($k));
}

function api_check(array $b): void
{
    $machine = $b['machine'];
    if (empty($b['key'])) {
        fail('no_key', 'Chưa có key (đang dùng gói Miễn phí).');
    }
    $k = key_row(strtoupper((string)$b['key']));
    if ($k && $k['status'] === 'merged' && $k['merged_into']) {
        $k = key_row($k['merged_into']);
    }
    if (!$k) {
        fail('bad_key', 'Key không tồn tại.', 404);
    }
    if ($k['status'] === 'revoked') {
        fail('revoked', 'Key đã bị khóa. Liên hệ người bán.', 403);
    }
    if ($k['machine'] !== $machine) {
        fail('moved', 'Key đã được chuyển sang máy khác.', 403);
    }
    if ((int)$k['expires_at'] !== 0 && (int)$k['expires_at'] <= now()) {
        fail('expired', 'Key đã hết hạn. Nhập key mới để gia hạn.', 403);
    }
    db()->prepare('UPDATE keys SET last_check_at=? WHERE id=?')->execute([now(), $k['id']]);
    json_out(['ok' => true, 'full_key' => $k['key']] + key_token($k));
}

// ---------------------------------------------------------------- mua key: VietQR + SePay (dùng chung tài khoản của Voice AI)

function bank(): ?array
{
    $b = opt('bank');
    return (is_array($b) && !empty($b['account'])) ? $b : null;
}

function tlv(string $id, string $value): string
{
    return $id . str_pad((string)strlen($value), 2, '0', STR_PAD_LEFT) . $value;
}

function crc16(string $s): string
{
    $crc = 0xFFFF;
    for ($i = 0, $n = strlen($s); $i < $n; $i++) {
        $crc ^= ord($s[$i]) << 8;
        for ($j = 0; $j < 8; $j++) {
            $crc = ($crc & 0x8000) ? (($crc << 1) ^ 0x1021) & 0xFFFF : ($crc << 1) & 0xFFFF;
        }
    }
    return strtoupper(str_pad(dechex($crc), 4, '0', STR_PAD_LEFT));
}

function vietqr(string $bin, string $account, int $amount, string $memo): string
{
    $merchant = tlv('00', 'A000000727') . tlv('01', tlv('00', $bin) . tlv('01', $account)) . tlv('02', 'QRIBFTTA');
    $s = tlv('00', '01') . tlv('01', '12') . tlv('38', $merchant) . tlv('53', '704')
        . tlv('54', (string)$amount) . tlv('58', 'VN') . tlv('62', tlv('08', $memo)) . '6304';
    return $s . crc16($s);
}

function prefix(): string
{
    return strtoupper((string)opt('code_prefix', 'VAI'));
}

/** Mã đơn không trùng với đơn của Voice AI (cùng tiền tố để khớp cấu trúc mã thanh toán đã khai báo trên SePay). */
function new_order_code(): string
{
    $voice = null;
    $vf = voice_private() . '/data/orders.sqlite';
    if (is_file($vf)) {
        try {
            $voice = new PDO('sqlite:' . $vf);
        } catch (Throwable $e) {
            $voice = null;
        }
    }
    for ($i = 0; $i < 10; $i++) {
        $code = prefix() . rand_from(ORDER_ALPHABET, 8);
        $q = db()->prepare('SELECT 1 FROM orders WHERE code=?');
        $q->execute([$code]);
        if ($q->fetchColumn()) {
            continue;
        }
        if ($voice) {
            try {
                $v = $voice->prepare('SELECT 1 FROM orders WHERE code=?');
                $v->execute([$code]);
                if ($v->fetchColumn()) {
                    continue;
                }
            } catch (Throwable $e) {
            }
        }
        return $code;
    }
    throw new RuntimeException('Không tạo được mã đơn');
}

function order_public(array $o, bool $withKey): array
{
    $b = bank() ?? [];
    $status = $o['status'];
    if ($status === 'pending' && (int)$o['expires_at'] < now()) {
        $status = 'expired';
    }
    $p = plan($o['plan']);
    $out = [
        'ok' => true, 'code' => $o['code'], 'status' => $status, 'plan' => $p ? $p['name'] : $o['plan'], 'plan_code' => $o['plan'],
        'amount' => (int)$o['amount'], 'content' => $o['code'], 'expires_in' => max(0, (int)$o['expires_at'] - now()),
        'bank' => ['id' => $b['name'] ?? '', 'name' => $b['holder'] ?? '', 'account' => $b['account'] ?? '', 'bin' => $b['bin'] ?? ''],
        'qr_payload' => isset($b['bin']) ? vietqr((string)$b['bin'], (string)$b['account'], (int)$o['amount'], $o['code']) : '',
        'qr_url' => isset($b['bin']) ? 'https://img.vietqr.io/image/' . rawurlencode((string)$b['bin']) . '-' . rawurlencode((string)$b['account'])
            . '-compact2.png?amount=' . (int)$o['amount'] . '&addInfo=' . rawurlencode($o['code']) . '&accountName=' . rawurlencode((string)($b['holder'] ?? '')) : '',
    ];
    if ($withKey && $status === 'paid') {
        $out['key'] = $o['key'];
    }
    return $out;
}

function api_order(array $b): void
{
    if (!bank() || !opt('sepay_api_key')) {
        fail('no_payment', 'Chưa bật thanh toán tự động.');
    }
    $p = plan((string)($b['plan'] ?? ''));
    if (!$p || !(int)$p['active']) {
        fail('bad_plan', 'Gói không tồn tại.', 404);
    }
    if (limited('order:' . client_ip(), 30, 3600)) {
        fail('rate', 'Bạn thao tác quá nhanh, vui lòng thử lại sau.', 429);
    }
    $pdo = db();
    // dùng lại đơn đang chờ cùng máy + cùng gói + cùng giá
    $q = $pdo->prepare('SELECT * FROM orders WHERE machine=? AND plan=? AND amount=? AND status="pending" AND expires_at>? ORDER BY created_at DESC LIMIT 1');
    $q->execute([$b['machine'], $p['code'], (int)$p['price'], now()]);
    $o = $q->fetch();
    if (!$o) {
        $code = new_order_code();
        $pdo->prepare('INSERT INTO orders (code, plan, amount, machine, created_at, expires_at) VALUES (?,?,?,?,?,?)')
            ->execute([$code, $p['code'], (int)$p['price'], $b['machine'], now(), now() + 60 * (int)(cfg()['order_ttl_minutes'] ?? 30)]);
        $q = $pdo->prepare('SELECT * FROM orders WHERE code=?');
        $q->execute([$code]);
        $o = $q->fetch();
        telegram("🛒 [Video AI] Đơn mới (chờ thanh toán)\nGói: {$p['name']}\nSố tiền: " . money((int)$p['price']) . "\nMã đơn: $code");
    }
    json_out(order_public($o, false));
}

function api_order_status(string $code, string $machine): void
{
    $q = db()->prepare('SELECT * FROM orders WHERE code=?');
    $q->execute([strtoupper($code)]);
    $o = $q->fetch();
    if (!$o || ($o['machine'] && $machine && $o['machine'] !== $machine)) {
        fail('not_found', 'Không thấy đơn hàng.', 404);
    }
    json_out(order_public($o, true));
}

function order_exists(string $code): bool
{
    if ($code === '') {
        return false;
    }
    $q = db()->prepare('SELECT 1 FROM orders WHERE code=?');
    $q->execute([$code]);
    return (bool)$q->fetchColumn();
}

/** Lấy mã đơn từ dữ liệu SePay: trường code, hoặc tìm trong nội dung chuyển khoản. */
function code_from(array $d): string
{
    $pre = preg_quote(prefix(), '/');
    $code = strtoupper((string)($d['code'] ?? ''));
    if (!preg_match('/^' . $pre . '[A-Z0-9]{8}$/', $code)) {
        $code = preg_match('/' . $pre . '[A-Z0-9]{8}/i', (string)($d['content'] ?? ''), $m) ? strtoupper($m[0]) : '';
    }
    return $code;
}

function sepay_authorized(string $authHeader): bool
{
    $k = trim((string)opt('sepay_api_key', ''));
    return $k !== '' && hash_equals('Apikey ' . $k, trim($authHeader));
}

/** Xử lý tiền về cho đơn Video AI (đã xác thực). Trả về kết quả để ghi log. */
function handle_payment(array $d): string
{
    if (($d['transferType'] ?? 'in') !== 'in') {
        return 'out';
    }
    $sepayId = (string)($d['id'] ?? $d['referenceCode'] ?? '');
    $amount = (int)($d['transferAmount'] ?? 0);
    $content = (string)($d['content'] ?? '');
    $code = code_from($d);
    if ($sepayId === '') {
        $sepayId = 'noid-' . $code . '-' . $amount;
    }
    $pdo = db();
    $pdo->exec('BEGIN IMMEDIATE');
    $msg = null;
    try {
        $ins = $pdo->prepare('INSERT OR IGNORE INTO transactions (sepay_id, code, amount, content, result, created_at) VALUES (?,?,?,?,?,?)');
        $ins->execute([$sepayId, $code, $amount, mb_substr($content, 0, 300), 'received', now()]);
        if ($ins->rowCount() === 0) {
            $pdo->exec('COMMIT');
            return 'duplicate';
        }
        $q = $pdo->prepare('SELECT * FROM orders WHERE code=?');
        $q->execute([$code]);
        $o = $q->fetch();
        if (!$o) {
            $result = 'unknown_order';
        } elseif ($o['status'] === 'paid') {
            $result = 'duplicate_payment';
            $msg = "⚠️ [Video AI] Đơn $code ĐÃ thanh toán trước đó, vừa nhận thêm " . money($amount) . '. Cần hoàn tiền thủ công.';
        } elseif ($amount < (int)$o['amount']) {
            $result = 'underpaid';
            $pdo->prepare('UPDATE orders SET status="review", sepay_id=?, paid_amount=?, note=? WHERE code=?')
                ->execute([$sepayId, $amount, 'Thiếu tiền', $code]);
            $msg = "⚠️ [Video AI] Đơn $code THIẾU TIỀN: nhận " . money($amount) . ', cần ' . money((int)$o['amount']) . '. Xử lý tay trong trang quản trị.';
        } else {
            $p = plan($o['plan']);
            $key = new_key();
            $late = ((int)$o['expires_at'] < now()) ? 'thanh toán sau khi đơn hết hạn' : '';
            $pdo->prepare('INSERT INTO keys (key, plan, days, price, order_code, customer, note, created_at) VALUES (?,?,?,?,?,?,?,?)')
                ->execute([$key, $o['plan'], $p ? (int)$p['days'] : 30, $amount, $code, null, trim('Tự động qua SePay ' . $late), now()]);
            $pdo->prepare('UPDATE orders SET status="paid", key=?, paid_at=?, sepay_id=?, paid_amount=?, note=? WHERE code=?')
                ->execute([$key, now(), $sepayId, $amount, $late, $code]);
            $result = 'paid';
            $msg = "✅ [Video AI] ĐƠN ĐÃ THANH TOÁN\nGói: " . ($p['name'] ?? $o['plan']) . "\nSố tiền: " . money($amount) . "\nMã đơn: $code\nKey: $key";
        }
        $pdo->prepare('UPDATE transactions SET result=? WHERE sepay_id=?')->execute([$result, $sepayId]);
        $pdo->exec('COMMIT');
    } catch (Throwable $e) {
        $pdo->exec('ROLLBACK');
        throw $e;
    }
    if ($msg) {
        telegram($msg);
    }
    event('payment', null, null, "$code $amount -> $result");
    log_line("Webhook $sepayId code=$code amount=$amount -> $result");
    return $result;
}

function telegram(string $text): bool
{
    $token = trim((string)opt('telegram_token', ''));
    $chat = trim((string)opt('telegram_chat_id', ''));
    if ($token === '' || $chat === '' || !function_exists('curl_init')) {
        return false;
    }
    $ch = curl_init('https://api.telegram.org/bot' . $token . '/sendMessage');
    curl_setopt_array($ch, [CURLOPT_POST => true, CURLOPT_POSTFIELDS => ['chat_id' => $chat, 'text' => $text],
        CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 8, CURLOPT_CONNECTTIMEOUT => 5]);
    $res = curl_exec($ch);
    $code = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    return $res !== false && $code === 200;
}

function request_auth_header(): string
{
    foreach (['HTTP_AUTHORIZATION', 'REDIRECT_HTTP_AUTHORIZATION'] as $k) {
        if (!empty($_SERVER[$k])) {
            return (string)$_SERVER[$k];
        }
    }
    if (function_exists('getallheaders')) {
        foreach (getallheaders() as $k => $v) {
            if (strcasecmp($k, 'Authorization') === 0) {
                return (string)$v;
            }
        }
    }
    return '';
}
