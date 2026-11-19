<?php
declare(strict_types=1);
// API trang quản trị CHUNG: Video AI (key online) + Voice AI (đơn, giao dịch, cấp key offline thay CapKey).
// Đăng nhập bằng admin_password trong active_private/video/config.php (gửi qua header X-Admin-Token).

$priv = getenv('ACTIVE_PRIVATE') ?: __DIR__ . '/../../active_private';
require_once (getenv('VIDEOAI_PRIVATE') ?: $priv . '/video') . '/lib.php';
$voiceLib = $priv . '/lib.php';
$hasVoice = is_file($voiceLib) && is_file($priv . '/config.php');
if ($hasVoice) {
    require_once $voiceLib;          // hàm toàn cục của Voice AI: cfg(), db(), make_key(), parse_machine(), fulfil_order()...
}

use VideoAI as V;

function out($data, int $status = 200): void
{
    V\json_out($data, $status);
}

function bad(string $msg, int $status = 400): void
{
    V\json_out(['ok' => false, 'message' => $msg], $status);
}

try {
    $token = (string)($_SERVER['HTTP_X_ADMIN_TOKEN'] ?? '');
    $pass = (string)(V\cfg()['admin_password'] ?? '');
    if (strlen($pass) < 10 || str_starts_with($pass, 'DAT_')) {
        bad('Chưa đặt admin_password (ít nhất 10 ký tự) trong active_private/video/config.php', 500);
    }
    if (!hash_equals($pass, $token)) {
        if (V\limited('admin_fail:' . V\client_ip(), 8, 600)) {
            bad('Thử sai quá nhiều lần, đợi 10 phút.', 429);
        }
        bad('Sai mật khẩu quản trị', 401);
    }
    $a = preg_replace('/[^a-z_]/', '', (string)($_GET['a'] ?? ''));
    $b = json_decode((string)file_get_contents('php://input'), true) ?: [];
    $t = V\now();
    $pdo = V\db();
    $one = function (string $sql, array $args = []) use ($pdo) {
        $q = $pdo->prepare($sql);
        $q->execute($args);
        return $q->fetchColumn();
    };

    $dlDir = __DIR__ . '/../video/download';              // bộ cài để phần mềm tự cập nhật
    $host = preg_match('/^[a-z0-9.-]+(:\d+)?$/i', (string)($_SERVER['HTTP_HOST'] ?? '')) ? $_SERVER['HTTP_HOST'] : 'localhost';
    $dlBase = 'https://' . $host . '/video/download/';

    // ============================================================ VIDEO AI
    switch ($a) {
        case 'info':
            out(['ok' => true, 'voice' => $hasVoice, 'video_pubkey' => V\public_key_b64url(),
                 'payment' => (bool)(V\bank() && V\opt('sepay_api_key'))]);
        case 'stats':
            $d0 = strtotime('today');
            out(['ok' => true,
                'active' => (int)$one('SELECT COUNT(*) FROM keys WHERE status="active" AND (expires_at=0 OR expires_at>?)', [$t]),
                'unused' => (int)$one('SELECT COUNT(*) FROM keys WHERE status="new"'),
                'pending' => (int)$one('SELECT COUNT(*) FROM orders WHERE status="pending" AND expires_at>?', [$t]),
                'review' => (int)$one('SELECT COUNT(*) FROM orders WHERE status="review"'),
                'revenue_today' => (int)$one('SELECT COALESCE(SUM(price),0) FROM keys WHERE created_at>? AND status!="revoked"', [$d0]),
                'revenue_30d' => (int)$one('SELECT COALESCE(SUM(price),0) FROM keys WHERE created_at>? AND status!="revoked"', [$t - 30 * V\DAY]),
                'revenue_all' => (int)$one('SELECT COALESCE(SUM(price),0) FROM keys WHERE status!="revoked"'),
                'payment' => (bool)(V\bank() && V\opt('sepay_api_key'))]);
        case 'keys':
            $q = '%' . trim((string)($_GET['q'] ?? '')) . '%';
            $st = $pdo->prepare('SELECT * FROM keys WHERE key LIKE ? OR IFNULL(customer,"") LIKE ? OR IFNULL(note,"") LIKE ? OR IFNULL(machine,"") LIKE ? ORDER BY id DESC LIMIT 300');
            $st->execute([$q, $q, $q, $q]);
            out(['ok' => true, 'keys' => $st->fetchAll(), 'now' => $t]);
        case 'create':
            $p = V\plan((string)($b['plan'] ?? ''));
            if (!$p) {
                bad('Gói không tồn tại');
            }
            $n = min(max((int)($b['count'] ?? 1), 1), 200);
            $days = ($b['days'] ?? '') !== '' ? (int)$b['days'] : (int)$p['days'];
            $price = ($b['price'] ?? '') !== '' ? (int)$b['price'] : (int)$p['price'];
            $made = [];
            $st = $pdo->prepare('INSERT INTO keys (key, plan, days, price, customer, note, created_at) VALUES (?,?,?,?,?,?,?)');
            for ($i = 0; $i < $n; $i++) {
                $k = V\new_key();
                $st->execute([$k, $p['code'], $days, $price, ($b['customer'] ?? '') ?: null, ($b['note'] ?? '') ?: null, $t]);
                $made[] = $k;
            }
            V\event('admin_create', $made[0], null, "$n key {$p['code']}");
            out(['ok' => true, 'keys' => $made]);
        case 'revoke':
            $pdo->prepare('UPDATE keys SET status="revoked" WHERE key=?')->execute([$b['key'] ?? '']);
            V\event('admin_revoke', $b['key'] ?? '');
            out(['ok' => true]);
        case 'unrevoke':
            $pdo->prepare('UPDATE keys SET status=CASE WHEN machine IS NULL THEN "new" ELSE "active" END WHERE key=? AND status="revoked"')->execute([$b['key'] ?? '']);
            out(['ok' => true]);
        case 'extend':
            $k = V\key_row((string)($b['key'] ?? ''));
            if (!$k) {
                bad('Không thấy key');
            }
            $d = (int)($b['days'] ?? 0);
            if ($k['status'] === 'new') {
                $pdo->prepare('UPDATE keys SET days=days+? WHERE id=?')->execute([$d, $k['id']]);
            } elseif ((int)$k['expires_at'] !== 0) {
                $pdo->prepare('UPDATE keys SET expires_at=? WHERE id=?')->execute([max((int)$k['expires_at'], $t) + $d * V\DAY, $k['id']]);
            }
            V\event('admin_extend', $k['key'], null, "+$d");
            out(['ok' => true]);
        case 'reset_machine':
            $pdo->prepare('UPDATE keys SET machine=NULL, last_transfer_at=NULL WHERE key=?')->execute([$b['key'] ?? '']);
            V\event('admin_reset', $b['key'] ?? '');
            out(['ok' => true]);
        case 'note':
            $pdo->prepare('UPDATE keys SET customer=?, note=? WHERE key=?')->execute([($b['customer'] ?? '') ?: null, ($b['note'] ?? '') ?: null, $b['key'] ?? '']);
            out(['ok' => true]);
        case 'plans':
            if (($_SERVER['REQUEST_METHOD'] ?? '') === 'POST') {
                $st = $pdo->prepare('UPDATE plans SET name=?, days=?, price=?, badge=?, active=? WHERE code=?');
                foreach (($b['plans'] ?? []) as $p) {
                    $st->execute([(string)$p['name'], (int)$p['days'], (int)$p['price'], ($p['badge'] ?? '') ?: null, !empty($p['active']) ? 1 : 0, (string)$p['code']]);
                }
            }
            out(['ok' => true, 'plans' => $pdo->query('SELECT * FROM plans ORDER BY sort')->fetchAll()]);
        case 'guides':
            if (($_SERVER['REQUEST_METHOD'] ?? '') === 'POST') {
                foreach (($b['guides'] ?? []) as $page => $u) {
                    $u = trim((string)$u);
                    if (!preg_match('/^[a-z0-9_]{2,40}$/', (string)$page)) {
                        continue;
                    }
                    if ($u === '') {
                        $pdo->prepare('DELETE FROM guides WHERE page=?')->execute([$page]);
                        continue;
                    }
                    if (!preg_match('#^https://#i', $u)) {
                        bad("Link của \"$page\" phải bắt đầu bằng https://");
                    }
                    $pdo->prepare('INSERT INTO guides (page, url, updated_at) VALUES (?,?,?) ON CONFLICT(page) DO UPDATE SET url=excluded.url, updated_at=excluded.updated_at')
                        ->execute([$page, $u, $t]);
                }
                V\event('admin_guides');
            }
            out(['ok' => true, 'guides' => $pdo->query('SELECT page, url, updated_at FROM guides')->fetchAll()]);
        case 'orders':
            out(['ok' => true, 'orders' => $pdo->query('SELECT * FROM orders ORDER BY created_at DESC LIMIT 300')->fetchAll(), 'now' => $t]);
        case 'order_paid':           // xác nhận tay đơn chờ / thiếu tiền → tạo key
            $q = $pdo->prepare('SELECT * FROM orders WHERE code=?');
            $q->execute([(string)($b['code'] ?? '')]);
            $o = $q->fetch();
            if (!$o || $o['status'] === 'paid') {
                bad('Không thấy đơn hoặc đơn đã thanh toán');
            }
            $p = V\plan($o['plan']);
            $k = V\new_key();
            $pdo->prepare('INSERT INTO keys (key, plan, days, price, order_code, note, created_at) VALUES (?,?,?,?,?,?,?)')
                ->execute([$k, $o['plan'], $p ? (int)$p['days'] : 30, (int)($o['paid_amount'] ?: $o['amount']), $o['code'], 'Xác nhận tay', $t]);
            $pdo->prepare('UPDATE orders SET status="paid", key=?, paid_at=?, note=? WHERE code=?')->execute([$k, $t, 'Xác nhận tay', $o['code']]);
            V\event('admin_order_paid', $k, null, $o['code']);
            out(['ok' => true, 'key' => $k]);
        case 'events':
            out(['ok' => true, 'events' => $pdo->query('SELECT * FROM events ORDER BY id DESC LIMIT 300')->fetchAll()]);
        case 'releases':             // danh sách bản đã phát hành + file .exe đang có trong video/download/
            $files = [];
            foreach (glob($dlDir . '/*.exe') ?: [] as $f) {
                $files[] = ['name' => basename($f), 'size' => filesize($f), 'mtime' => filemtime($f),
                    'version' => preg_match('/(\d+\.\d+(?:\.\d+){0,2})\.exe$/i', basename($f), $mm) ? $mm[1] : ''];
            }
            usort($files, fn($x, $y) => $y['mtime'] <=> $x['mtime']);
            $latest = V\latest_release();
            out(['ok' => true, 'releases' => $pdo->query('SELECT * FROM releases ORDER BY id DESC LIMIT 100')->fetchAll(),
                'files' => $files, 'latest_id' => $latest ? (int)$latest['id'] : 0, 'base' => $dlBase, 'dir_ok' => is_dir($dlDir)]);
        case 'release_publish':      // phát hành bản mới: chọn file trong video/download/ (tự tính SHA-256) hoặc dán link https
            $ver = trim((string)($b['version'] ?? ''));
            if (!V\valid_version($ver)) {
                bad('Số phiên bản phải dạng 1.5.0');
            }
            $min = trim((string)($b['min_version'] ?? ''));
            if ($min !== '' && !V\valid_version($min)) {
                bad('"Bắt buộc với bản thấp hơn" phải dạng 1.5.0 hoặc để trống');
            }
            $file = basename((string)($b['file'] ?? ''));
            $url = trim((string)($b['url'] ?? ''));
            $sha = strtolower(trim((string)($b['sha256'] ?? '')));
            $size = 0;
            if ($file !== '') {
                $path = $dlDir . '/' . $file;
                if (!preg_match('/\.exe$/i', $file) || !is_file($path)) {
                    bad('Không thấy file ' . $file . ' trong thư mục video/download/');
                }
                @set_time_limit(300);
                $sha = hash_file('sha256', $path);
                $size = filesize($path);
                $url = $dlBase . rawurlencode($file);
            } else {
                if (!preg_match('#^https://\S+$#i', $url)) {
                    bad('Chọn một file bộ cài, hoặc dán link tải bắt đầu bằng https://');
                }
                if ($sha !== '' && !preg_match('/^[0-9a-f]{64}$/', $sha)) {
                    bad('Mã SHA-256 phải gồm 64 ký tự 0-9a-f (hoặc để trống)');
                }
            }
            $pdo->prepare('INSERT INTO releases (version, url, sha256, size, notes, mandatory, min_version, active, created_at) VALUES (?,?,?,?,?,?,?,1,?)')
                ->execute([$ver, $url, $sha ?: null, $size ?: null, mb_substr(trim((string)($b['notes'] ?? '')), 0, 4000),
                    !empty($b['mandatory']) ? 1 : 0, $min ?: null, $t]);
            V\event('admin_release', null, null, $ver . ' ' . $url);
            out(['ok' => true, 'version' => $ver, 'sha256' => $sha, 'size' => $size, 'url' => $url]);
        case 'release_toggle':       // ngừng phát hành (khách không nhận bản này nữa) / phát hành lại
            $pdo->prepare('UPDATE releases SET active=? WHERE id=?')->execute([!empty($b['active']) ? 1 : 0, (int)($b['id'] ?? 0)]);
            V\event('admin_release_toggle', null, null, (int)($b['id'] ?? 0) . ' → ' . (!empty($b['active']) ? 'on' : 'off'));
            out(['ok' => true]);
    }

    // ============================================================ VOICE AI (dùng chính lib.php của Voice AI)
    if (str_starts_with($a, 'v_')) {
        if (!$hasVoice) {
            bad('Không thấy máy chủ Voice AI (active_private/lib.php, config.php)');
        }
        $vc = \cfg();
        $vdb = \db();
        $vone = function (string $sql, array $args = []) use ($vdb) {
            $q = $vdb->prepare($sql);
            $q->execute($args);
            return $q->fetchColumn();
        };
        switch ($a) {
            case 'v_stats':
                $d0 = strtotime('today');
                out(['ok' => true,
                    'paid_all' => (int)$vone('SELECT COUNT(*) FROM orders WHERE status="paid"'),
                    'pending' => (int)$vone('SELECT COUNT(*) FROM orders WHERE status="pending" AND expires_at>?', [$t]),
                    'review' => (int)$vone('SELECT COUNT(*) FROM orders WHERE status="review"'),
                    'revenue_today' => (int)$vone('SELECT COALESCE(SUM(paid_amount),0) FROM orders WHERE status="paid" AND paid_at>?', [$d0]),
                    'revenue_30d' => (int)$vone('SELECT COALESCE(SUM(paid_amount),0) FROM orders WHERE status="paid" AND paid_at>?', [$t - 30 * 86400]),
                    'revenue_all' => (int)$vone('SELECT COALESCE(SUM(paid_amount),0) FROM orders WHERE status="paid"'),
                    'manual_keys' => (int)$one('SELECT COUNT(*) FROM events WHERE product="voiceai" AND kind="capkey"')]);
            case 'v_plans':
                $pl = [];
                foreach ($vc['plans'] as $code => $p) {
                    $pl[] = ['code' => $code, 'name' => $p['name'], 'days' => $p['days'], 'price' => (int)$p['price'], 'type' => (int)$p['type']];
                }
                out(['ok' => true, 'plans' => $pl]);
            case 'v_orders':
                out(['ok' => true, 'orders' => $vdb->query('SELECT * FROM orders ORDER BY created_at DESC LIMIT 300')->fetchAll(), 'now' => $t]);
            case 'v_transactions':
                out(['ok' => true, 'transactions' => $vdb->query('SELECT * FROM transactions ORDER BY created_at DESC LIMIT 300')->fetchAll()]);
            case 'v_version':         // thông báo bản mới của Voice AI = file version.json ở thư mục subdomain
                $vf = __DIR__ . '/../version.json';
                if (($_SERVER['REQUEST_METHOD'] ?? '') === 'POST') {
                    $ver = trim((string)($b['version'] ?? ''));
                    $url = trim((string)($b['url'] ?? ''));
                    if (!V\valid_version($ver)) {
                        bad('Số phiên bản phải dạng 1.2.0');
                    }
                    if ($url !== '' && !preg_match('#^https://\S+$#i', $url)) {
                        bad('Link tải phải bắt đầu bằng https://');
                    }
                    $hl = array_values(array_filter(array_map('trim', preg_split('/\R/', (string)($b['highlights'] ?? '')))));
                    if (is_file($vf)) {
                        @copy($vf, $vf . '.bak');
                    }
                    $ok = file_put_contents($vf, json_encode(['version' => $ver, 'url' => $url, 'highlights' => array_slice($hl, 0, 6)],
                        JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . "\n", LOCK_EX);
                    if ($ok === false) {
                        bad('Không ghi được version.json (kiểm tra quyền ghi thư mục subdomain)');
                    }
                    V\event('admin_voice_version', null, null, $ver, 'voiceai');
                }
                $v = is_file($vf) ? json_decode((string)file_get_contents($vf), true) : null;
                out(['ok' => true, 'version' => is_array($v) ? $v : ['version' => '', 'url' => '', 'highlights' => []]]);
            case 'v_capkey':          // cấp key Voice AI thủ công (giống công cụ CapKey)
                $hex = \parse_machine((string)($b['machine'] ?? ''));
                if ($hex === null) {
                    bad('Mã máy Voice AI không hợp lệ (dạng MH-XXXX-XXXX-XXXX-XXXX)');
                }
                $pc = (string)($b['plan'] ?? '');
                if (!isset($vc['plans'][$pc])) {
                    bad('Gói không tồn tại');
                }
                $key = \make_key((int)$vc['plans'][$pc]['type'], $hex);
                $mtext = 'MH-' . implode('-', str_split($hex, 4));
                V\event('capkey', $key, $mtext, trim($vc['plans'][$pc]['name'] . ' · ' . ($b['customer'] ?? '') . ' · ' . ($b['note'] ?? ''), ' ·'), 'voiceai');
                out(['ok' => true, 'key' => $key, 'machine' => $mtext, 'plan' => $vc['plans'][$pc]['name']]);
            case 'v_capkeys':
                out(['ok' => true, 'keys' => $pdo->query('SELECT * FROM events WHERE product="voiceai" AND kind="capkey" ORDER BY id DESC LIMIT 300')->fetchAll()]);
            case 'v_order_paid':       // xác nhận tay đơn Voice AI (chờ / thiếu tiền) → tạo key bằng hàm của Voice AI
                $q = $vdb->prepare('SELECT * FROM orders WHERE code=?');
                $q->execute([(string)($b['code'] ?? '')]);
                $o = $q->fetch();
                if (!$o || $o['status'] === 'paid') {
                    bad('Không thấy đơn hoặc đơn đã thanh toán');
                }
                $vdb->exec('BEGIN IMMEDIATE');
                $key = \fulfil_order($o, (int)($o['paid_amount'] ?: $o['amount']), (string)($o['sepay_id'] ?: 'admin-' . $t), 'Xác nhận tay');
                $vdb->exec('COMMIT');
                V\event('v_order_paid', $key, $o['machine_id'], $o['code'], 'voiceai');
                out(['ok' => true, 'key' => $key]);
        }
    }
    bad('Không có chức năng này', 404);
} catch (Throwable $e) {
    V\log_line('admin/api.php: ' . $e->getMessage());
    out(['ok' => false, 'message' => 'Lỗi máy chủ: ' . $e->getMessage()], 500);
}
