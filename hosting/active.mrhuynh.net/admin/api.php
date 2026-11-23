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

// GCloud Hub (miễn phí, chỉ cập nhật) — thêm mới, không ảnh hưởng Video AI / Voice AI.
$gcloudLib = (getenv('GCLOUDHUB_PRIVATE') ?: $priv . '/gcloudhub') . '/lib.php';
$hasGCloud = is_file($gcloudLib);
if ($hasGCloud) {
    require_once $gcloudLib;          // namespace GCloudHub
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
            out(['ok' => true, 'voice' => $hasVoice, 'gcloud' => $hasGCloud, 'video_pubkey' => V\public_key_b64url(),
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
        case 'installs':             // Video AI: số máy đã cài / đang hoạt động + danh sách máy
            out(['ok' => true, 'stats' => V\install_stats(), 'list' => V\install_list((int)($b['limit'] ?? 200))]);
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
            $sp = V\site_installer_path(__DIR__);
            $site = ['url' => V\site_installer_url(), 'local' => $sp !== null,
                     'size' => $sp ? filesize($sp) : 0, 'mtime' => $sp ? filemtime($sp) : 0, 'version' => ''];
            if ($sp) {
                $fh = @fopen($sp, 'rb');
                $site['version'] = $fh ? V\pe_product_version((string)fread($fh, 8 << 20)) : '';
                if ($fh) {
                    fclose($fh);
                }
            }
            $mp = V\site_installer_path(__DIR__, 'mac');
            $mi = V\site_mac_info(__DIR__);
            $site_mac = ['url' => V\site_installer_url('mac'), 'local' => $mp !== null, 'size' => $mp ? filesize($mp) : (int)($mi['size'] ?? 0),
                         'mtime' => $mp ? filemtime($mp) : 0, 'version' => (string)($mi['version'] ?? ''), 'arch' => (string)($mi['arch'] ?? '')];
            $latestMac = V\latest_release('mac');
            out(['ok' => true, 'releases' => $pdo->query('SELECT * FROM releases ORDER BY id DESC LIMIT 100')->fetchAll(),
                'files' => $files, 'latest_id' => $latest ? (int)$latest['id'] : 0, 'base' => $dlBase, 'dir_ok' => is_dir($dlDir),
                'site' => $site, 'site_mac' => $site_mac, 'latest_mac_id' => $latestMac ? (int)$latestMac['id'] : 0]);
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
            $os = ($b['os'] ?? '') === 'mac' ? 'mac' : 'win';
            if ($os === 'mac') {            // macOS: file DUY NHẤT mrhuynh.net/downloads/video_ai_mrhuynh_mac.dmg (+ mac.json)
                if (empty($b['site'])) {
                    bad('Bản macOS phát hành từ file trên trang tải (video_ai_mrhuynh_mac.dmg).');
                }
                @set_time_limit(900);
                $mp = V\site_installer_path(__DIR__, 'mac');
                $base = V\site_installer_url('mac');
                try {
                    $info = V\inspect_installer($mp ?? ($base . '?check=' . $t));
                } catch (Throwable $e) {
                    bad('Không đọc được ' . $base . ' – đã tải dist/downloads-mac-upload.zip lên và Extract chưa? (' . $e->getMessage() . ')');
                }
                if ($info['size'] < 5 << 20 || !$info['dmg']) {
                    bad('File ' . V\SITE_FILE_MAC . ' trên trang tải KHÔNG phải bộ cài macOS (.dmg).');
                }
                $mi = V\site_mac_info(__DIR__);
                $mv = (string)($mi['version'] ?? '');
                if ($mv !== '' && version_compare($mv, $ver) !== 0) {
                    bad('File .dmg trên trang tải là bản ' . $mv . ' nhưng bạn ghi ' . $ver . '. Hãy ghi đúng ' . $mv . '.');
                }
                if (!empty($mi['sha256']) && strtolower($mi['sha256']) !== $info['sha256']) {
                    bad('mac.json không khớp với file .dmg trên trang tải – hãy giải nén lại đủ cả 2 file từ downloads-mac-upload.zip.');
                }
                $sha = $info['sha256'];
                $size = $info['size'];
                $url = $base . '?v=' . rawurlencode($ver);
            } elseif (!empty($b['site'])) {       // file DUY NHẤT trên trang tải mrhuynh.net/downloads/video_ai_mrhuynh_win.exe
                @set_time_limit(900);
                $sp = V\site_installer_path(__DIR__);
                $base = V\site_installer_url();
                try {
                    $info = V\inspect_installer($sp ?? ($base . '?check=' . $t));      // không đọc được ổ đĩa → tải qua https
                } catch (Throwable $e) {
                    bad('Không đọc được ' . $base . ' – đã tải file lên thư mục downloads chưa? (' . $e->getMessage() . ')');
                }
                if ($info['size'] < 5 << 20 || !$info['inno']) {
                    bad('File ' . V\SITE_FILE . ' trên trang tải KHÔNG phải bộ cài (Setup). Hãy tải lên file từ dist\\downloads\\ '
                        . '(hoặc giải nén dist\\downloads-upload.zip) rồi bấm Phát hành lại.');
                }
                if ($info['version'] !== '' && version_compare($info['version'], $ver) !== 0) {
                    bad('File trên trang tải là bản ' . $info['version'] . ' nhưng bạn ghi ' . $ver
                        . '. Phần mềm của khách sẽ cài lại mãi. Hãy ghi đúng ' . $info['version'] . ' hoặc tải lên bộ cài bản ' . $ver . '.');
                }
                $sha = $info['sha256'];
                $size = $info['size'];
                $url = $base . '?v=' . rawurlencode($ver);      // ?v= để bộ nhớ đệm (Cloudflare, trình duyệt) không trả file cũ
            } elseif ($file !== '') {
                $path = $dlDir . '/' . $file;
                if (!preg_match('/\.exe$/i', $file) || !is_file($path)) {
                    bad('Không thấy file ' . $file . ' trong thư mục video/download/');
                }
                if (preg_match('/(\d+\.\d+(?:\.\d+){0,2})\.exe$/i', $file, $fm) && version_compare($fm[1], $ver) !== 0) {
                    bad('File ' . $file . ' là bản ' . $fm[1] . ' nhưng bạn ghi số phiên bản ' . $ver
                        . '. Phần mềm của khách sẽ cài lại mãi vì không lên được bản ' . $ver . '. Hãy ghi đúng ' . $fm[1]
                        . ' hoặc build lại bản ' . $ver . '.');
                }
                @set_time_limit(300);
                if (!V\is_inno_setup($path)) {
                    bad('File ' . $file . ' KHÔNG phải bộ cài (Setup) — có thể là file chạy VideoAI-MrHuynh.exe lấy từ thư mục dist\\VideoAI-MrHuynh '
                        . '(file đó cần thư mục _internal đi kèm, khách cài sẽ lỗi "Failed to load Python DLL"). '
                        . 'Hãy tải file dist\\VideoAI-MrHuynh-Setup-x.y.z.exe (nặng vài trăm MB) lên rồi chọn file đó.');
                }
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
            $pdo->prepare('INSERT INTO releases (version, url, sha256, size, notes, mandatory, min_version, active, created_at, os) VALUES (?,?,?,?,?,?,?,1,?,?)')
                ->execute([$ver, $url, $sha ?: null, $size ?: null, mb_substr(trim((string)($b['notes'] ?? '')), 0, 4000),
                    !empty($b['mandatory']) ? 1 : 0, $min ?: null, $t, $os]);
            V\event('admin_release', null, null, $os . ' ' . $ver . ' ' . $url);
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
            case 'v_plans_save':          // lưu sửa giá Voice AI → ghi active_private/voice_plans.json (cfg() đọc đè)
                $vplans = [];
                foreach (($b['plans'] ?? []) as $p) {
                    $code = (string)($p['code'] ?? '');
                    if ($code !== '' && isset($vc['plans'][$code])) {
                        $vplans[$code] = ['name' => (string)($p['name'] ?? ''), 'days' => ((int)($p['days'] ?? 0)) ?: null, 'price' => (int)($p['price'] ?? 0)];
                    }
                }
                file_put_contents(\private_dir() . '/voice_plans.json', json_encode($vplans, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT));
                out(['ok' => true]);
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
    // ============================================================ GCLOUD HUB (miễn phí · chỉ cập nhật)
    if (str_starts_with($a, 'g_')) {
        if (!$hasGCloud) {
            bad('Không thấy module GCloud Hub (active_private/gcloudhub/lib.php)');
        }
        $gdb = \GCloudHub\db();
        $gDlDir = __DIR__ . '/../gcloudhub/download';
        $gDlBase = 'https://' . $host . '/gcloudhub/download/';
        switch ($a) {
            case 'g_stats':
                $act30 = (int)$gdb->query('SELECT COUNT(*) FROM installs WHERE last_at>' . ($t - 30 * 86400))->fetchColumn();
                $act1 = (int)$gdb->query('SELECT COUNT(*) FROM installs WHERE last_at>' . ($t - 86400))->fetchColumn();
                $total = (int)$gdb->query('SELECT COUNT(*) FROM installs')->fetchColumn();
                $checks = (int)$gdb->query('SELECT COALESCE(SUM(checks),0) FROM installs')->fetchColumn();
                $L = \GCloudHub\latest_release('win');
                out(['ok' => true, 'installs_total' => $total, 'active_30d' => $act30, 'active_1d' => $act1,
                    'checks' => $checks, 'latest' => $L ? $L['version'] : '',
                    'guide_url' => \GCloudHub\meta_get('guide_url', '')]);
            case 'g_guide_save':
                $gu = trim((string)($b['guide_url'] ?? ''));
                if ($gu !== '' && !preg_match('#^https://\S+$#i', $gu)) {
                    bad('Link hướng dẫn phải bắt đầu bằng https:// (hoặc để trống để ẩn)');
                }
                \GCloudHub\meta_set('guide_url', $gu);
                \GCloudHub\event('guide_url', $gu !== '' ? $gu : '(xóa)');
                out(['ok' => true, 'guide_url' => $gu]);
            case 'g_releases':
                $files = [];
                foreach (glob($gDlDir . '/*.exe') ?: [] as $f) {
                    $files[] = ['name' => basename($f), 'size' => filesize($f), 'mtime' => filemtime($f),
                        'version' => preg_match('/(\d+\.\d+(?:\.\d+){0,2})[^\/]*\.exe$/i', basename($f), $mm) ? $mm[1] : ''];
                }
                usort($files, fn($x, $y) => $y['mtime'] <=> $x['mtime']);
                $L = \GCloudHub\latest_release('win');
                $sp = \GCloudHub\site_installer_path(__DIR__);
                $site = ['url' => \GCloudHub\site_installer_url(), 'local' => $sp !== null,
                         'size' => $sp ? filesize($sp) : 0, 'mtime' => $sp ? filemtime($sp) : 0, 'version' => ''];
                if ($sp) {
                    $fh = @fopen($sp, 'rb');
                    $site['version'] = $fh ? \GCloudHub\pe_product_version((string)fread($fh, 8 << 20)) : '';
                    if ($fh) {
                        fclose($fh);
                    }
                }
                $Marm = \GCloudHub\latest_release_key('mac-arm64');
                $Mx64 = \GCloudHub\latest_release_key('mac-x64');
                out(['ok' => true, 'releases' => $gdb->query('SELECT * FROM releases ORDER BY id DESC LIMIT 100')->fetchAll(),
                    'files' => $files, 'latest_id' => $L ? (int)$L['id'] : 0, 'base' => $gDlBase,
                    'dir_ok' => is_dir($gDlDir), 'site' => $site,
                    'mac' => ['arm64' => $Marm ? $Marm['version'] : '', 'x64' => $Mx64 ? $Mx64['version'] : '',
                        'base' => \GCloudHub\meta_get('mac_dmg_base', 'https://github.com/alltoolsmax/gcloud-hub-build/releases/download/latest/')]]);
            case 'g_release_publish':
                $ver = trim((string)($b['version'] ?? ''));
                if (!\GCloudHub\valid_version($ver)) {
                    bad('Số phiên bản phải dạng 1.5.0');
                }
                $min = trim((string)($b['min_version'] ?? ''));
                if ($min !== '' && !\GCloudHub\valid_version($min)) {
                    bad('"Bắt buộc với bản thấp hơn" phải dạng 1.5.0 hoặc để trống');
                }
                $file = basename((string)($b['file'] ?? ''));
                $url = trim((string)($b['url'] ?? ''));
                $sha = strtolower(trim((string)($b['sha256'] ?? '')));
                $size = 0;
                if (!empty($b['site'])) {                 // file DUY NHẤT trên trang tải mrhuynh.net/downloads/gcloud_hub_win.exe
                    @set_time_limit(900);
                    $sp = \GCloudHub\site_installer_path(__DIR__);
                    $base = \GCloudHub\site_installer_url();
                    try {
                        $info = \GCloudHub\inspect_installer($sp ?? ($base . '?check=' . $t));
                    } catch (Throwable $e) {
                        bad('Không đọc được ' . $base . ' - đã tải file lên thư mục downloads chưa? (' . $e->getMessage() . ')');
                    }
                    if ($info['size'] < 1 << 20 || !$info['is_exe']) {
                        bad('File ' . \GCloudHub\SITE_FILE . ' trên trang tải không phải file .exe hợp lệ.');
                    }
                    if ($info['version'] !== '' && version_compare($info['version'], $ver) !== 0) {
                        bad('File trên trang tải là bản ' . $info['version'] . ' nhưng bạn ghi ' . $ver . '. Hãy ghi đúng ' . $info['version'] . '.');
                    }
                    $sha = $info['sha256'];
                    $size = $info['size'];
                    $url = $base . '?v=' . rawurlencode($ver);
                } elseif ($file !== '') {
                    $path = $gDlDir . '/' . $file;
                    if (!preg_match('/\.exe$/i', $file) || !is_file($path)) {
                        bad('Không thấy file ' . $file . ' trong thư mục gcloudhub/download/');
                    }
                    if (preg_match('/(\d+\.\d+(?:\.\d+){0,2})[^\/]*\.exe$/i', $file, $fm) && version_compare($fm[1], $ver) !== 0) {
                        bad('File ' . $file . ' là bản ' . $fm[1] . ' nhưng bạn ghi ' . $ver . '. Hãy ghi đúng ' . $fm[1] . '.');
                    }
                    @set_time_limit(300);
                    $info = \GCloudHub\inspect_installer($path);
                    if ($info['size'] < 1 << 20 || !$info['is_exe']) {
                        bad('File ' . $file . ' không phải file .exe hợp lệ.');
                    }
                    $sha = $info['sha256'];
                    $size = $info['size'];
                    $url = $gDlBase . rawurlencode($file);
                } else {
                    if (!preg_match('#^https://\S+$#i', $url)) {
                        bad('Chọn một file trong thư mục tải, hoặc dán link tải bắt đầu bằng https://');
                    }
                    if ($sha !== '' && !preg_match('/^[0-9a-f]{64}$/', $sha)) {
                        bad('Mã SHA-256 phải gồm 64 ký tự 0-9a-f (hoặc để trống)');
                    }
                }
                $gdb->prepare('INSERT INTO releases (version, url, sha256, size, notes, mandatory, min_version, active, os, created_at) VALUES (?,?,?,?,?,?,?,1,?,?)')
                    ->execute([$ver, $url, $sha ?: null, $size ?: null, mb_substr(trim((string)($b['notes'] ?? '')), 0, 4000),
                        !empty($b['mandatory']) ? 1 : 0, $min ?: null, 'win', $t]);
                \GCloudHub\event('release', $ver . ' ' . $url);
                out(['ok' => true, 'version' => $ver, 'sha256' => $sha, 'size' => $size, 'url' => $url]);
            case 'g_release_mac':
                // Phát hành bản Mac: tạo 2 dòng (arm64 + x64) trỏ tới 2 file .dmg build sẵn trên GitHub.
                $ver = trim((string)($b['version'] ?? ''));
                if (!\GCloudHub\valid_version($ver)) {
                    bad('Số phiên bản phải dạng 1.0.8');
                }
                $min = trim((string)($b['min_version'] ?? ''));
                if ($min !== '' && !\GCloudHub\valid_version($min)) {
                    bad('"Bắt buộc với bản thấp hơn" phải dạng 1.0.8 hoặc để trống');
                }
                $base = trim((string)($b['base'] ?? ''));
                if ($base === '') {
                    $base = \GCloudHub\meta_get('mac_dmg_base', 'https://github.com/alltoolsmax/gcloud-hub-build/releases/download/latest/');
                }
                if (!preg_match('#^https://\S+/$#i', $base)) {
                    bad('Link gốc file .dmg phải bắt đầu bằng https:// và kết thúc bằng dấu /');
                }
                \GCloudHub\meta_set('mac_dmg_base', $base);
                $mand = !empty($b['mandatory']) ? 1 : 0;
                $notes = mb_substr(trim((string)($b['notes'] ?? '')), 0, 4000);
                foreach (['arm64', 'x64'] as $arch) {
                    $url = $base . 'GCloudHub-' . $ver . '-' . $arch . '.dmg';
                    $gdb->prepare('INSERT INTO releases (version, url, sha256, size, notes, mandatory, min_version, active, os, created_at) VALUES (?,?,?,?,?,?,?,1,?,?)')
                        ->execute([$ver, $url, null, null, $notes, $mand, $min ?: null, 'mac-' . $arch, $t]);
                }
                \GCloudHub\event('release_mac', $ver . ' ' . $base);
                out(['ok' => true, 'version' => $ver,
                    'arm64' => $base . 'GCloudHub-' . $ver . '-arm64.dmg',
                    'x64' => $base . 'GCloudHub-' . $ver . '-x64.dmg']);
            case 'g_release_toggle':
                $gdb->prepare('UPDATE releases SET active=? WHERE id=?')->execute([!empty($b['active']) ? 1 : 0, (int)($b['id'] ?? 0)]);
                \GCloudHub\event('release_toggle', (int)($b['id'] ?? 0) . ' -> ' . (!empty($b['active']) ? 'on' : 'off'));
                out(['ok' => true]);
            case 'g_events':
                out(['ok' => true, 'events' => $gdb->query('SELECT * FROM events ORDER BY id DESC LIMIT 300')->fetchAll()]);
        }
    }

    bad('Không có chức năng này', 404);
} catch (Throwable $e) {
    V\log_line('admin/api.php: ' . $e->getMessage());
    out(['ok' => false, 'message' => 'Lỗi máy chủ: ' . $e->getMessage()], 500);
}
