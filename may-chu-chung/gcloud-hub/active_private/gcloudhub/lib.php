<?php
declare(strict_types=1);

// GCloud Hub - Mr. Huỳnh · thư viện máy chủ CẬP NHẬT (PHP + SQLite), chạy chung hosting với Video AI / Voice AI.
// GCloud Hub MIỄN PHÍ - KHÔNG có key/gói/thanh toán. Chỉ quản lý phát hành bản mới + thống kê lượt cập nhật.
// Toàn bộ nằm trong namespace GCloudHub để KHÔNG trùng tên hàm với Video AI / Voice AI.

namespace GCloudHub;

use PDO;
use RuntimeException;
use Throwable;

const DAY = 86400;
const PRODUCT = 'gcloudhub';

// Tên file DUY NHẤT trên trang tải (khách tải lần đầu và phần mềm tự cập nhật đều dùng file này).
const SITE_FILE = 'gcloud_hub_win.exe';

function dir(): string
{
    return getenv('GCLOUDHUB_PRIVATE') ?: __DIR__;
}

/** Múi giờ: mượn config Video AI nếu có, không bắt buộc. */
function boot_timezone(): void
{
    static $done = false;
    if ($done) {
        return;
    }
    $done = true;
    $tz = 'Asia/Ho_Chi_Minh';
    $vc = dirname(dir()) . '/video/config.php';
    if (is_file($vc)) {
        try {
            $c = require $vc;
            if (is_array($c) && !empty($c['timezone'])) {
                $tz = (string)$c['timezone'];
            }
        } catch (Throwable $e) {
        }
    }
    date_default_timezone_set($tz);
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
    @file_put_contents($d . '/gcloudhub.log', '[' . date('Y-m-d H:i:s') . '] ' . $msg . "\n", FILE_APPEND | LOCK_EX);
}

function db(): PDO
{
    static $pdo = null;
    if ($pdo) {
        return $pdo;
    }
    boot_timezone();
    $d = dir() . '/data';
    if (!is_dir($d)) {
        @mkdir($d, 0700, true);
    }
    $pdo = new PDO('sqlite:' . $d . '/gcloudhub.sqlite');
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
    $pdo->exec('PRAGMA journal_mode=WAL');
    $pdo->exec('PRAGMA busy_timeout=8000');
    $pdo->exec('CREATE TABLE IF NOT EXISTS releases (id INTEGER PRIMARY KEY AUTOINCREMENT, version TEXT NOT NULL, url TEXT NOT NULL,
        sha256 TEXT, size INTEGER, notes TEXT, mandatory INTEGER NOT NULL DEFAULT 0, min_version TEXT, active INTEGER NOT NULL DEFAULT 1,
        os TEXT NOT NULL DEFAULT "win", created_at INTEGER NOT NULL)');
    // mỗi máy cài 1 dòng (ẩn danh: chỉ là id ngẫu nhiên do phần mềm tự sinh) → đếm số máy đang dùng & lượt cập nhật
    $pdo->exec('CREATE TABLE IF NOT EXISTS installs (iid TEXT PRIMARY KEY, first_at INTEGER NOT NULL, last_at INTEGER NOT NULL,
        checks INTEGER NOT NULL DEFAULT 1, version TEXT, os TEXT)');
    $pdo->exec('CREATE INDEX IF NOT EXISTS installs_last ON installs(last_at)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL, kind TEXT NOT NULL, detail TEXT)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS rate (k TEXT NOT NULL, ts INTEGER NOT NULL)');
    $pdo->exec('CREATE INDEX IF NOT EXISTS rate_k ON rate(k, ts)');
    // cấu hình nhỏ (key/value): ví dụ link video hướng dẫn hiển thị trong phần mềm
    $pdo->exec('CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)');
    return $pdo;
}

/** Đọc một cấu hình key/value (trả $def nếu chưa đặt). */
function meta_get(string $k, string $def = ''): string
{
    try {
        $st = db()->prepare('SELECT v FROM meta WHERE k=?');
        $st->execute([$k]);
        $v = $st->fetchColumn();
        return $v === false ? $def : (string)$v;
    } catch (Throwable $e) {
        return $def;
    }
}

/** Ghi một cấu hình key/value. */
function meta_set(string $k, string $v): void
{
    db()->prepare('INSERT INTO meta (k, v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v')->execute([$k, $v]);
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

function fail(string $code, string $message, int $status = 400): void
{
    json_out(['ok' => false, 'code' => $code, 'message' => $message], $status);
}

function event(string $kind, ?string $detail = null): void
{
    try {
        db()->prepare('INSERT INTO events (at, kind, detail) VALUES (?,?,?)')
            ->execute([now(), $kind, $detail !== null ? mb_substr($detail, 0, 500) : null]);
    } catch (Throwable $e) {
    }
}

function limited(string $k, int $max, int $window = 60): bool
{
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

function valid_version(string $v): bool
{
    return (bool)preg_match('/^\d{1,4}(\.\d{1,4}){1,3}$/', $v);
}

// ------------------------------------------------------------------ cập nhật phần mềm

function latest_release(string $os = 'win'): ?array
{
    return latest_release_key($os === 'mac' ? 'mac' : 'win');
}

/** Bản mới nhất theo khóa os cụ thể: 'win', 'mac-arm64', 'mac-x64'. */
function latest_release_key(string $key): ?array
{
    $st = db()->prepare('SELECT * FROM releases WHERE active=1 AND os=?');
    $st->execute([$key]);
    $rows = $st->fetchAll();
    usort($rows, fn($a, $b) => version_compare($b['version'], $a['version']) ?: ((int)$b['id'] <=> (int)$a['id']));
    return $rows[0] ?? null;
}

/** Ghi nhận 1 máy đang dùng (ẩn danh). $iid do phần mềm tự sinh (uuid), không chứa thông tin cá nhân. */
function record_install(?string $iid, ?string $version, string $os): void
{
    if (!is_string($iid) || !preg_match('/^[A-Za-z0-9_-]{8,64}$/', $iid)) {
        return;
    }
    try {
        db()->prepare('INSERT INTO installs (iid, first_at, last_at, checks, version, os) VALUES (?,?,?,1,?,?)
            ON CONFLICT(iid) DO UPDATE SET last_at=excluded.last_at, checks=checks+1, version=excluded.version, os=excluded.os')
            ->execute([$iid, now(), now(), $version, $os]);
    } catch (Throwable $e) {
    }
}

/** Bản Mac mới nhất GitHub đã build + công bố (gcloud_mac.json tên cố định), nhớ 10 phút. Lỗi mạng → bản nhớ cũ. */
function mac_github_release(): ?array
{
    $old = json_decode(meta_get('gh_mac', ''), true);
    $old = is_array($old) && ($old['version'] ?? '') !== '' ? $old : null;
    if ($old && (time() - (int)($old['_at'] ?? 0)) < 600) {
        return $old;
    }
    $repo = 'alltoolsmax/gcloud-hub-build';
    $src = getenv('GCLOUDHUB_MAC_JSON') ?: 'https://github.com/' . $repo . '/releases/latest/download/gcloud_mac.json';
    $ctx = stream_context_create(['http' => ['timeout' => 8, 'follow_location' => 1, 'max_redirects' => 5,
        'header' => "User-Agent: GCloudHub-Server\r\nCache-Control: no-cache\r\n"]]);
    $j = json_decode((string)@file_get_contents($src, false, $ctx), true);
    if (!is_array($j) || !valid_version((string)($j['version'] ?? ''))) {
        return $old;
    }
    $j['_at'] = time();
    $j['_base'] = 'https://github.com/' . $repo . '/releases/download/v' . $j['version'] . '/';
    meta_set('gh_mac', (string)json_encode($j));
    return $j;
}

/** Endpoint phần mềm gọi để kiểm tra bản mới:  GET /gcloudhub/v1/app/version?os=win&iid=...&v=... */
function api_version(): void
{
    header('Cache-Control: no-store');
    $isMac = ($_GET['os'] ?? '') === 'mac';
    $arch = ($_GET['arch'] ?? '') === 'arm64' ? 'arm64' : 'x64';
    $key = $isMac ? 'mac-' . $arch : 'win';
    record_install($_GET['iid'] ?? null, isset($_GET['v']) ? (string)$_GET['v'] : null, $key);
    $guide = meta_get('guide_url', '');
    if ($isMac) {                       // Mac: tự cập nhật thẳng từ bản GitHub build (không cần bấm Phát hành)
        $m = mac_github_release();
        $chip = $arch === 'arm64' ? 'apple' : 'intel';
        if ($m && !empty($m[$chip]['sha256'])) {
            json_out(['ok' => true, 'version' => $m['version'], 'url' => $m['_base'] . $m[$chip]['file'],
                'sha256' => (string)$m[$chip]['sha256'], 'size' => (int)$m[$chip]['size'], 'notes' => '',
                'mandatory' => false, 'min_version' => '', 'released_at' => (int)$m['_at'], 'guide_url' => $guide]);
        }
    }
    $r = latest_release_key($key);
    if (!$r) {
        json_out(['ok' => true, 'version' => '0.0.0', 'guide_url' => $guide]);
    }
    json_out(['ok' => true, 'version' => $r['version'], 'url' => $r['url'], 'sha256' => (string)$r['sha256'],
        'size' => (int)$r['size'], 'notes' => (string)$r['notes'], 'mandatory' => (bool)$r['mandatory'],
        'min_version' => (string)($r['min_version'] ?? ''), 'released_at' => (int)$r['created_at'],
        'guide_url' => $guide]);
}

// ---------------------------------------------------------------- đọc bộ cài (SHA-256, dung lượng, phiên bản)

/** Số phiên bản ghi trong file .exe (ProductVersion/FileVersion trong tài nguyên PE, chuỗi UTF-16) - '' nếu không thấy. */
function pe_product_version(string $head): string
{
    foreach (['ProductVersion', 'FileVersion'] as $k) {
        $key = mb_convert_encoding($k, 'UTF-16LE', 'UTF-8') . "\0\0";
        $p = strpos($head, $key);
        if ($p === false) {
            continue;
        }
        $rest = ltrim(substr($head, $p + strlen($key), 80), "\0");
        if (preg_match('/^((?:[0-9.]\x00){1,40})/', $rest, $m)) {
            $v = str_replace("\0", '', $m[1]);
            $v = preg_replace('/(\.0)+$/', '', $v) ?: $v;
            if (preg_match('/^\d+\.\d+(\.\d+){0,2}$/', $v)) {
                return $v;
            }
        }
    }
    return '';
}

/** Đọc file bộ cài (trên ổ đĩa hoặc qua https) một lượt: SHA-256, dung lượng, phiên bản, có phải .exe Windows (MZ). */
function inspect_installer(string $src): array
{
    $ctx = stream_context_create(['http' => ['timeout' => 120, 'header' => "Cache-Control: no-cache\r\n", 'user_agent' => 'GCloudHub-Admin']]);
    $f = @fopen($src, 'rb', false, $ctx);
    if (!$f) {
        throw new RuntimeException('Không mở được ' . $src);
    }
    $h = hash_init('sha256');
    $size = 0;
    $head = '';
    $first2 = '';
    while (!feof($f)) {
        $chunk = fread($f, 1 << 20);
        if ($chunk === false || $chunk === '') {
            if (feof($f)) {
                break;
            }
            continue;
        }
        if ($first2 === '') {
            $first2 = substr($chunk, 0, 2);
        }
        hash_update($h, $chunk);
        $size += strlen($chunk);
        if (strlen($head) < (8 << 20)) {
            $head .= substr($chunk, 0, (8 << 20) - strlen($head));
        }
    }
    fclose($f);
    return ['sha256' => hash_final($h), 'size' => $size, 'version' => pe_product_version($head), 'is_exe' => $first2 === 'MZ'];
}

/** Thư mục download trên ổ đĩa (để tính SHA-256 trực tiếp, nhanh hơn tải qua https). */
function download_dir(string $adminDir): string
{
    return dirname($adminDir) . '/gcloudhub/download';
}

/** File DUY NHẤT trên trang tải mrhuynh.net/downloads/gcloud_hub_win.exe (tùy chọn, giống Video AI). */
function site_installer_path(string $adminDir): ?string
{
    $home = dirname($adminDir, 2);
    foreach ([$home . '/mrhuynh.net/downloads', $home . '/public_html/downloads', $home . '/downloads', dirname($home) . '/public_html/downloads'] as $d) {
        $f = $d . '/' . SITE_FILE;
        if (@is_file($f) && @is_readable($f)) {
            return $f;
        }
    }
    return null;
}

function site_installer_url(): string
{
    return 'https://mrhuynh.net/downloads/' . SITE_FILE;
}
