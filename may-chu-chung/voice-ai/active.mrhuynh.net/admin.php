<?php
declare(strict_types=1);
require (getenv('ACTIVE_PRIVATE') ?: __DIR__ . '/../active_private') . '/lib.php';

// Trang quản trị bản quyền Voice AI - Mr.Huỳnh:  https://active.mrhuynh.net/admin.php
// Mật khẩu đặt trong active_private/config.php: 'admin_password' (hoặc 'admin_password_hash').

const SESSION_IDLE = 7200;      // 2 giờ không thao tác thì đăng xuất
const LOGIN_MAX_FAILS = 5;      // sai quá số lần này trong 15 phút thì khoá 15 phút
const PAGE_SIZE = 50;

$nonce = base64_encode(random_bytes(16));
header('Content-Type: text/html; charset=utf-8');
header('Cache-Control: no-store');
header('X-Frame-Options: DENY');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: no-referrer');
header('X-Robots-Tag: noindex, nofollow');
header("Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-$nonce'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'");

function h($v): string
{
    return htmlspecialchars((string)$v, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function is_https(): bool
{
    return (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off')
        || (($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https');
}

function start_session(): void
{
    $dir = private_dir() . '/sessions';
    if (!is_dir($dir)) {
        @mkdir($dir, 0700, true);
    }
    if (is_dir($dir) && is_writable($dir)) {
        session_save_path($dir);
    }
    session_name('va_admin');
    session_set_cookie_params(['lifetime' => 0, 'path' => '/', 'secure' => is_https(), 'httponly' => true, 'samesite' => 'Strict']);
    session_start();
}

function client_ip(): string
{
    return (string)($_SERVER['REMOTE_ADDR'] ?? '?');
}

function password_ok(string $given): bool
{
    $c = cfg();
    $hash = (string)($c['admin_password_hash'] ?? '');
    if ($hash !== '') {
        return password_verify($given, $hash);
    }
    $plain = (string)($c['admin_password'] ?? '');
    return $plain !== '' && hash_equals($plain, $given);
}

function password_configured(): bool
{
    $c = cfg();
    return (string)($c['admin_password_hash'] ?? '') !== '' || (string)($c['admin_password'] ?? '') !== '';
}

function csrf(): string
{
    if (empty($_SESSION['csrf'])) {
        $_SESSION['csrf'] = bin2hex(random_bytes(16));
    }
    return $_SESSION['csrf'];
}

function check_csrf(): void
{
    if (!hash_equals((string)($_SESSION['csrf'] ?? ''), (string)($_POST['csrf'] ?? ''))) {
        http_response_code(403);
        exit('Phiên không hợp lệ. Hãy tải lại trang.');
    }
}

function redirect(string $q = ''): never
{
    header('Location: admin.php' . $q);
    exit;
}

function flash(string $msg, bool $error = false): void
{
    $_SESSION['flash'] = ['m' => $msg, 'e' => $error];
}

function page_head(string $title): void
{
    echo '<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        . '<meta name="robots" content="noindex"><title>' . h($title) . '</title><style>'
        . ':root{--bg:#0f172a;--card:#1e293b;--line:#334155;--tx:#e2e8f0;--mut:#94a3b8;--pri:#7c3aed;--ok:#22c55e;--warn:#f59e0b;--bad:#ef4444}'
        . '*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.5 system-ui,Segoe UI,Roboto,sans-serif;padding:20px}'
        . 'h1{margin:0;font-size:22px}h2{font-size:16px;margin:26px 0 10px}a{color:#a78bfa}.mut{color:var(--mut);font-size:12px}'
        . '.top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap;margin-bottom:16px}'
        . '.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}'
        . '.stat{background:var(--card);border-radius:10px;padding:14px 16px}.stat b{display:block;font-size:22px;margin:4px 0}'
        . '.card{background:var(--card);border-radius:10px;padding:16px}'
        . '.row{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end}.row label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--mut)}'
        . 'input,select,textarea{background:#0f172a;color:var(--tx);border:1px solid var(--line);border-radius:8px;padding:9px 11px;font:inherit}'
        . 'textarea{width:100%;min-height:90px}input:focus,select:focus,textarea:focus{outline:2px solid var(--pri);border-color:transparent}'
        . 'button,.btn{background:var(--pri);color:#fff;border:0;border-radius:8px;padding:9px 16px;font:inherit;font-weight:600;cursor:pointer;text-decoration:none;display:inline-block}'
        . 'button.sec,.btn.sec{background:#0e7490}button.ghost{background:transparent;border:1px solid var(--line);color:var(--tx)}button.sm{padding:4px 10px;font-size:12px}'
        . 'button.bad{background:var(--bad)}button.ok{background:#15803d}'
        . '.tablewrap{overflow-x:auto;border-radius:10px}table{width:100%;border-collapse:collapse;background:var(--card)}'
        . 'th{text-align:left;padding:10px 12px;background:#26344b;font-size:12px}td{padding:9px 12px;border-top:1px solid var(--line);vertical-align:top}'
        . '.tag{display:inline-block;border-radius:99px;padding:2px 9px;font-size:12px;font-weight:600}'
        . '.t-paid{background:#14532d;color:#86efac}.t-pending{background:#3f3f46;color:#d4d4d8}.t-review{background:#78350f;color:#fcd34d}'
        . '.t-expired,.t-cancelled{background:#3f3f46;color:#a1a1aa}.t-manual{background:#1e3a8a;color:#bfdbfe}'
        . '.msg{padding:11px 14px;border-radius:10px;margin-bottom:14px;background:#14532d;color:#bbf7d0}.msg.e{background:#7f1d1d;color:#fecaca}'
        . '.key{font-family:ui-monospace,Consolas,monospace;font-size:12px;word-break:break-all}.keybox{background:#0f172a;border:1px dashed var(--line);border-radius:8px;padding:10px;margin-top:8px}'
        . '.pager{display:flex;gap:8px;margin-top:12px;align-items:center}.login{max-width:360px;margin:12vh auto}'
        . '</style></head><body>';
}

function page_foot(string $nonce, string $js = ''): void
{
    echo '<script nonce="' . h($nonce) . '">' . $js . '</script></body></html>';
}

// ------------------------------------------------------------ không có mật khẩu thì không mở
if (!password_configured()) {
    page_head('Quản trị');
    echo '<div class="login card"><h1>Chưa đặt mật khẩu</h1><p>Mở <code>active_private/config.php</code> trên hosting, thêm dòng '
        . '<code>\'admin_password\' => \'mat-khau-dai-kho-doan\',</code> rồi tải lại trang này.</p></div>';
    page_foot($nonce);
    exit;
}

start_session();
$pdo = db();
$pdo->exec('CREATE TABLE IF NOT EXISTS admin_attempts (ip TEXT NOT NULL, ts INTEGER NOT NULL)');
$pdo->exec('CREATE INDEX IF NOT EXISTS admin_attempts_ip ON admin_attempts(ip, ts)');

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$logged = !empty($_SESSION['ok']) && (time() - (int)($_SESSION['seen'] ?? 0)) < SESSION_IDLE;
if ($logged) {
    $_SESSION['seen'] = time();
} elseif (!empty($_SESSION['ok'])) {
    session_unset();
    session_regenerate_id(true);
}

// ------------------------------------------------------------ đăng nhập
if (!$logged) {
    $error = '';
    if ($method === 'POST' && ($_POST['action'] ?? '') === 'login') {
        $pdo->prepare('DELETE FROM admin_attempts WHERE ts < ?')->execute([time() - 900]);
        $n = $pdo->prepare('SELECT COUNT(*) FROM admin_attempts WHERE ip = ?');
        $n->execute([client_ip()]);
        if ((int)$n->fetchColumn() >= LOGIN_MAX_FAILS) {
            $error = 'Sai quá nhiều lần. Vui lòng thử lại sau 15 phút.';
            log_line('Admin: IP ' . client_ip() . ' bị khoá tạm do sai mật khẩu nhiều lần');
        } elseif (password_ok((string)($_POST['password'] ?? ''))) {
            $pdo->prepare('DELETE FROM admin_attempts WHERE ip = ?')->execute([client_ip()]);
            session_regenerate_id(true);
            $_SESSION['ok'] = true;
            $_SESSION['seen'] = time();
            log_line('Admin: đăng nhập từ ' . client_ip());
            redirect();
        } else {
            $pdo->prepare('INSERT INTO admin_attempts (ip, ts) VALUES (?, ?)')->execute([client_ip(), time()]);
            log_line('Admin: sai mật khẩu từ ' . client_ip());
            sleep(1);
            $error = 'Mật khẩu không đúng.';
        }
    }
    page_head('Đăng nhập quản trị');
    echo '<form class="login card" method="post"><h1>Quản trị bản quyền</h1><p class="mut">Voice AI - Mr.Huỳnh</p>'
        . ($error ? '<div class="msg e">' . h($error) . '</div>' : '')
        . '<input type="hidden" name="action" value="login"><label class="mut">Mật khẩu</label>'
        . '<input type="password" name="password" autocomplete="current-password" style="width:100%;margin:6px 0 14px" autofocus required>'
        . '<button type="submit" style="width:100%">Đăng nhập</button></form>';
    page_foot($nonce);
    exit;
}

// ------------------------------------------------------------ hành động (POST)
$c = cfg();
if ($method === 'POST') {
    check_csrf();
    $action = (string)($_POST['action'] ?? '');

    if ($action === 'logout') {
        session_unset();
        session_destroy();
        redirect();
    }

    if ($action === 'telegram') {
        $sent = telegram('✅ Thử từ trang quản trị: Telegram đã kết nối.');
        flash($sent ? 'Đã gửi tin thử Telegram.' : 'Chưa gửi được: kiểm tra telegram_token và telegram_chat_id trong config.php.', !$sent);
        redirect();
    }

    if ($action === 'manual_key') {
        $machine = parse_machine((string)($_POST['machine'] ?? ''));
        $planCode = (string)($_POST['plan'] ?? '');
        $amount = max(0, (int)preg_replace('/\D/', '', (string)($_POST['amount'] ?? '0')));
        $note = mb_substr(trim((string)($_POST['note'] ?? '')), 0, 120);
        if ($machine === null) {
            flash('Mã máy phải có dạng MH-XXXX-XXXX-XXXX-XXXX (chữ số và A-F).', true);
            redirect();
        }
        if (!isset($c['plans'][$planCode])) {
            flash('Gói không tồn tại.', true);
            redirect();
        }
        $machineText = 'MH-' . implode('-', str_split($machine, 4));
        $plan = $c['plans'][$planCode];
        $key = make_key((int)$plan['type'], $machine);
        $code = 'TAY' . substr(order_code(), strlen((string)($c['code_prefix'] ?? 'VAI')));
        $pdo->prepare('INSERT INTO orders (code, machine_id, plan, amount, status, key, created_at, expires_at, paid_at, sepay_id, paid_amount, note) VALUES (?,?,?,?,\'paid\',?,?,?,?,\'manual\',?,?)')
            ->execute([$code, $machineText, $planCode, (int)$plan['price'], $key, time(), time(), time(), $amount, $note !== '' ? $note : 'Cấp tay']);
        log_line("Admin: cấp key tay $code gói $planCode máy $machineText");
        telegram("🔑 Cấp key tay\nGói: {$plan['name']}\nSố tiền ghi nhận: " . money($amount) . "\nMã: $code\nMáy: $machineText" . ($note !== '' ? "\nGhi chú: $note" : ''));
        $_SESSION['newkey'] = ['key' => $key, 'code' => $code, 'machine' => $machineText, 'plan' => $plan['name']];
        flash('Đã tạo key cho máy ' . $machineText . '. Sao chép key bên dưới gửi cho khách.');
        redirect();
    }

    if ($action === 'approve' || $action === 'cancel') {
        $code = (string)($_POST['code'] ?? '');
        $pdo->exec('BEGIN IMMEDIATE');
        try {
            $q = $pdo->prepare('SELECT * FROM orders WHERE code=?');
            $q->execute([$code]);
            $o = $q->fetch();
            if (!$o) {
                throw new RuntimeException('Không thấy đơn.');
            }
            if ($action === 'approve') {
                if ($o['status'] === 'paid') {
                    throw new RuntimeException('Đơn này đã có key rồi.');
                }
                fulfil_order($o, (int)($o['paid_amount'] ?? 0), (string)($o['sepay_id'] ?: 'manual'), 'Duyệt tay');
                log_line("Admin: duyệt tay đơn $code");
                flash("Đã duyệt đơn $code và tạo key. Khách mở lại app là nhận key.");
            } else {
                if ($o['status'] === 'paid') {
                    throw new RuntimeException('Đơn đã thanh toán, không huỷ được.');
                }
                $pdo->prepare('UPDATE orders SET status=\'cancelled\' WHERE code=?')->execute([$code]);
                log_line("Admin: huỷ đơn $code");
                flash("Đã huỷ đơn $code.");
            }
            $pdo->exec('COMMIT');
        } catch (Throwable $e) {
            $pdo->exec('ROLLBACK');
            flash($e->getMessage(), true);
        }
        redirect();
    }

    if ($action === 'announce') {
        $f = __DIR__ . '/announcement.json';
        $old = is_file($f) ? json_decode((string)file_get_contents($f), true) : [];
        $old = is_array($old) ? $old : [];
        $title = mb_substr(trim((string)($_POST['title'] ?? '')), 0, 80);
        $body = mb_substr(trim((string)($_POST['body'] ?? '')), 0, 600);
        $btnText = mb_substr(trim((string)($_POST['button_text'] ?? '')), 0, 30);
        $btnUrl = trim((string)($_POST['button_url'] ?? ''));
        if ($btnUrl !== '' && !preg_match('#^https://[^\s]+$#', $btnUrl)) {
            flash('Link nút phải bắt đầu bằng https:// và không có khoảng trắng.', true);
            redirect();
        }
        $badge = mb_substr(trim((string)($_POST['badge'] ?? '')), 0, 24);
        $secondary = mb_substr(trim((string)($_POST['secondary_text'] ?? '')), 0, 20);
        $expRaw = trim((string)($_POST['expires'] ?? ''));
        $exp = 0;
        if ($expRaw !== '') {
            $dt = DateTime::createFromFormat('Y-m-d H:i:s', $expRaw . ' 23:59:59', new DateTimeZone(cfg()['timezone'] ?? 'Asia/Ho_Chi_Minh'));
            if (!$dt) {
                flash('Ngày hết hạn phải đúng dạng năm-tháng-ngày.', true);
                redirect();
            }
            $exp = $dt->getTimestamp();
        }
        $enabled = !empty($_POST['enabled']);
        if ($enabled && $title === '' && $body === '') {
            flash('Cần nhập tiêu đề hoặc nội dung trước khi bật thông báo.', true);
            redirect();
        }
        // Đổi nội dung hoặc bấm "Hiện lại cho mọi người" thì tạo id mới để người đã đóng thấy lại.
        $hash = sha1(json_encode([$badge, $title, $body, $btnText, $btnUrl, $secondary]));
        $id = (string)($old['id'] ?? '');
        if ($id === '' || ($old['hash'] ?? '') !== $hash || !empty($_POST['reshow'])) {
            $id = (string)time();
        }
        $data = ['enabled' => $enabled, 'id' => $id, 'hash' => $hash, 'badge' => $badge, 'title' => $title, 'body' => $body,
            'button_text' => $btnText, 'button_url' => $btnUrl, 'secondary_text' => $secondary, 'expires_at' => $exp];
        $tmp = $f . '.tmp';
        if (file_put_contents($tmp, json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT), LOCK_EX) === false || !rename($tmp, $f)) {
            flash('Không ghi được announcement.json (kiểm tra quyền ghi thư mục).', true);
            redirect();
        }
        log_line('Admin: ' . ($enabled ? 'bật' : 'tắt') . ' thông báo popup (' . $id . ')');
        flash($enabled ? 'Đã lưu và đang BẬT thông báo popup.' : 'Đã lưu. Thông báo popup đang TẮT.');
        redirect();
    }

    if ($action === 'video') {
        $url = trim((string)($_POST['video_url'] ?? ''));
        if ($url !== '' && !preg_match('#^https://[^\s]+$#', $url)) {
            flash('Link video phải bắt đầu bằng https:// và không có khoảng trắng.', true);
            redirect();
        }
        $f = __DIR__ . '/video.json';
        $tmp = $f . '.tmp';
        if (file_put_contents($tmp, json_encode(['url' => $url], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES), LOCK_EX) === false || !rename($tmp, $f)) {
            flash('Không ghi được video.json (kiểm tra quyền ghi thư mục).', true);
            redirect();
        }
        log_line('Admin: ' . ($url === '' ? 'ẩn' : 'đổi') . ' link video hướng dẫn');
        flash($url === '' ? 'Đã lưu. Nút Xem Video hướng dẫn trong app sẽ ẩn.' : 'Đã lưu link video hướng dẫn. App cập nhật trong vòng vài phút.');
        redirect();
    }

    if ($action === 'release') {
        $f = __DIR__ . '/version.json';
        $cur = is_file($f) ? json_decode((string)file_get_contents($f), true) : null;
        if (!is_array($cur) || empty($cur['version'])) {
            flash('Chưa có version.json hợp lệ. Hãy tạo bằng công cụ KY-BAN-CAP-NHAT.bat rồi chép lên hosting.', true);
            redirect();
        }
        $url = trim((string)($_POST['url'] ?? ''));
        if (!preg_match('#^https://[^\s]+$#', $url)) {
            flash('Link tải phải bắt đầu bằng https:// và không có khoảng trắng.', true);
            redirect();
        }
        $lines = array_values(array_filter(array_map(fn($l) => mb_substr(trim($l), 0, 80), preg_split('/\R/', (string)($_POST['highlights'] ?? '')) ?: [])));
        $cur['url'] = $url;
        $cur['highlights'] = array_slice($lines, 0, 6);
        $tmp = $f . '.tmp';
        if (file_put_contents($tmp, json_encode($cur, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT), LOCK_EX) === false || !rename($tmp, $f)) {
            flash('Không ghi được version.json (kiểm tra quyền ghi thư mục).', true);
            redirect();
        }
        log_line('Admin: sửa version.json (link/điểm mới)');
        flash('Đã lưu link tải và điểm mới. Phiên bản và chữ ký giữ nguyên.');
        redirect();
    }
    redirect();
}

function telegram_ready(): bool
{
    $c = cfg();
    return trim((string)($c['telegram_token'] ?? '')) !== '' && trim((string)($c['telegram_chat_id'] ?? '')) !== '';
}

// ------------------------------------------------------------ xuất CSV
if (($_GET['export'] ?? '') === 'csv') {
    header('Content-Type: text/csv; charset=utf-8');
    header('Content-Disposition: attachment; filename="don-hang-' . date('Ymd-His') . '.csv"');
    $out = fopen('php://output', 'w');
    fwrite($out, "\xEF\xBB\xBF");
    fputcsv($out, ['Thoi gian', 'Ma don', 'Goi', 'So tien', 'Da nhan', 'Trang thai', 'Ma may', 'Nguon', 'Ghi chu', 'Key']);
    foreach ($pdo->query('SELECT * FROM orders ORDER BY created_at DESC') as $o) {
        fputcsv($out, [date('Y-m-d H:i:s', (int)$o['created_at']), $o['code'], $o['plan'], $o['amount'], $o['paid_amount'], $o['status'],
            $o['machine_id'], $o['sepay_id'] === 'manual' ? 'tay' : 'QR', $o['note'], $o['key']]);
    }
    exit;
}

// ------------------------------------------------------------ số liệu
$today = strtotime('today');
$month = strtotime('first day of this month 00:00:00');
$sum = function (int $from, bool $manual) use ($pdo): array {
    $cond = $manual ? "sepay_id='manual'" : "(sepay_id IS NULL OR sepay_id<>'manual')";
    $q = $pdo->prepare("SELECT COALESCE(SUM(paid_amount),0) s, COUNT(*) n FROM orders WHERE status='paid' AND paid_at>=? AND $cond");
    $q->execute([$from]);
    return $q->fetch() ?: ['s' => 0, 'n' => 0];
};
$qrToday = $sum($today, false);
$qrMonth = $sum($month, false);
$qrAll = $sum(0, false);
$manMonth = $sum($month, true);
$attention = (int)$pdo->query("SELECT COUNT(*) FROM orders WHERE status='review'")->fetchColumn();
$badTx = $pdo->prepare("SELECT COUNT(*) FROM transactions WHERE result IN ('unknown_order','no_code','duplicate_payment') AND created_at>?");
$badTx->execute([time() - 86400]);
$attention += (int)$badTx->fetchColumn();

// ------------------------------------------------------------ danh sách đơn
$search = trim((string)($_GET['q'] ?? ''));
$page = max(1, (int)($_GET['p'] ?? 1));
$where = '';
$args = [];
if ($search !== '') {
    $like = '%' . str_replace(['!', '%', '_'], ['!!', '!%', '!_'], $search) . '%';
    $where = "WHERE code LIKE ? ESCAPE '!' OR machine_id LIKE ? ESCAPE '!' OR COALESCE(note,'') LIKE ? ESCAPE '!' OR COALESCE(key,'') LIKE ? ESCAPE '!'";
    $args = [$like, $like, $like, $like];
}
$cnt = $pdo->prepare("SELECT COUNT(*) FROM orders $where");
$cnt->execute($args);
$total = (int)$cnt->fetchColumn();
$pages = max(1, (int)ceil($total / PAGE_SIZE));
$page = min($page, $pages);
$rows = $pdo->prepare("SELECT * FROM orders $where ORDER BY created_at DESC LIMIT " . PAGE_SIZE . ' OFFSET ' . (($page - 1) * PAGE_SIZE));
$rows->execute($args);
$orders = $rows->fetchAll();

$badTxRows = $pdo->query("SELECT * FROM transactions WHERE result IN ('unknown_order','no_code','duplicate_payment') ORDER BY created_at DESC LIMIT 10")->fetchAll();

$vf = __DIR__ . '/version.json';
$ver = is_file($vf) ? json_decode((string)file_get_contents($vf), true) : null;
$ver = is_array($ver) ? $ver : [];

$flash = $_SESSION['flash'] ?? null;
unset($_SESSION['flash']);
$newkey = $_SESSION['newkey'] ?? null;
unset($_SESSION['newkey']);

$statusLabel = ['paid' => 'Đã thanh toán', 'pending' => 'Chờ thanh toán', 'review' => 'Cần xem', 'expired' => 'Hết hạn đơn', 'cancelled' => 'Đã huỷ'];

page_head('Quản trị bản quyền');
echo '<div class="top"><div><h1>Quản trị bản quyền</h1><div class="mut">Voice AI - Mr.Huỳnh · PHP ' . h(PHP_VERSION) . '</div></div><div class="row" style="align-items:center">'
    . '<form method="post"><input type="hidden" name="csrf" value="' . h(csrf()) . '"><input type="hidden" name="action" value="telegram"><button class="sec" type="submit">Thử Telegram</button></form>'
    . '<a class="btn ghost" href="?export=csv">Xuất CSV</a>'
    . '<form method="post"><input type="hidden" name="csrf" value="' . h(csrf()) . '"><input type="hidden" name="action" value="logout"><button class="ghost" type="submit">Đăng xuất</button></form></div></div>';

if ($flash) {
    echo '<div class="msg' . ($flash['e'] ? ' e' : '') . '">' . h($flash['m']) . '</div>';
}
if ($newkey) {
    echo '<div class="card" style="margin-bottom:14px"><b>Key vừa tạo</b> · ' . h($newkey['plan']) . ' · ' . h($newkey['machine'])
        . '<div class="keybox key" id="newkey">' . h($newkey['key']) . '</div>'
        . '<p><button type="button" class="ok sm" data-copy="newkey">Sao chép key</button> <span class="mut">Mã: ' . h($newkey['code']) . '. Key chỉ hiện một lần ở đây, nhưng vẫn xem lại được trong bảng đơn hàng.</span></p></div>';
}

echo '<div class="stats">'
    . '<div class="stat"><span class="mut">Hôm nay (QR)</span><b>' . h(money((int)$qrToday['s'])) . '</b><span class="mut">' . (int)$qrToday['n'] . ' đơn</span></div>'
    . '<div class="stat"><span class="mut">Tháng này (QR)</span><b>' . h(money((int)$qrMonth['s'])) . '</b><span class="mut">' . (int)$qrMonth['n'] . ' đơn · cấp tay ' . (int)$manMonth['n'] . ' (' . h(money((int)$manMonth['s'])) . ')</span></div>'
    . '<div class="stat"><span class="mut">Tổng (QR)</span><b>' . h(money((int)$qrAll['s'])) . '</b><span class="mut">' . (int)$qrAll['n'] . ' đơn</span></div>'
    . '<div class="stat"><span class="mut">Đơn cần xem</span><b' . ($attention > 0 ? ' style="color:#fcd34d"' : '') . '>' . $attention . '</b><span class="mut">thiếu tiền / giao dịch lạ (24 giờ)</span></div></div>';

// Phát hành
$hasSig = !empty($ver['sha256']) && !empty($ver['signature']);
echo '<h2>Phát hành &amp; cập nhật</h2><div class="card">';
if ($ver) {
    echo '<p>Bản trong <code>version.json</code>: <b>' . h($ver['version'] ?? '?') . '</b> · tự cập nhật trong app: '
        . ($hasSig ? '<span class="tag t-paid">Có chữ ký</span>' : '<span class="tag t-review">Thiếu chữ ký (app chỉ mở link tải)</span>') . '</p>';
    echo '<form method="post"><input type="hidden" name="csrf" value="' . h(csrf()) . '"><input type="hidden" name="action" value="release">'
        . '<label class="mut">Link tải trực tiếp (https, .zip hoặc .exe)</label><input name="url" style="width:100%;margin:4px 0 10px" value="' . h($ver['url'] ?? '') . '">'
        . '<label class="mut">Điểm mới (mỗi dòng một ý, tối đa 6)</label><textarea name="highlights">' . h(implode("\n", (array)($ver['highlights'] ?? []))) . '</textarea>'
        . '<p class="mut">Số phiên bản và chữ ký không sửa ở đây: tạo lại bằng <b>KY-BAN-CAP-NHAT.bat</b> trên máy bạn rồi chép version.json lên hosting. Khoá ký không nằm trên máy chủ nên hosting bị lộ cũng không đẩy được file giả cho khách.</p>'
        . '<button type="submit">Lưu</button></form>';
} else {
    echo '<p>Chưa có <code>version.json</code>. Tạo bằng công cụ <b>KY-BAN-CAP-NHAT.bat</b> rồi chép lên hosting.</p>';
}
echo '</div>';

// Video hướng dẫn
$vdf = __DIR__ . '/video.json';
$vdj = is_file($vdf) ? json_decode((string)file_get_contents($vdf), true) : [];
$vdUrl = is_array($vdj) ? (string)($vdj['url'] ?? '') : '';
echo '<h2>Video hướng dẫn</h2><div class="card"><form method="post"><input type="hidden" name="csrf" value="' . h(csrf()) . '"><input type="hidden" name="action" value="video">'
    . '<label class="mut">Link video YouTube (https://...). Hiện thành nút "Xem Video hướng dẫn" ở đầu app. Để trống = ẩn nút.</label>'
    . '<input name="video_url" style="width:100%;margin:4px 0 10px" value="' . h($vdUrl) . '" placeholder="https://www.youtube.com/watch?v=...">'
    . '<p style="margin:0"><button type="submit">Lưu link video</button></p></form></div>';

// Thông báo popup
$af = __DIR__ . '/announcement.json';
$an = is_file($af) ? json_decode((string)file_get_contents($af), true) : [];
$an = is_array($an) ? $an : [];
$anOn = !empty($an['enabled']);
$anExp = (int)($an['expires_at'] ?? 0);
echo '<h2>Thông báo popup cho người dùng</h2><div class="card">';
echo '<p>Trạng thái: ' . ($anOn ? '<span class="tag t-paid">Đang BẬT</span>' : '<span class="tag t-review">Đang TẮT</span>')
    . ($anOn && $anExp > 0 && $anExp < time() ? ' <span class="tag t-review">Đã hết hạn</span>' : '') . ' <span class="mut">App kiểm tra mỗi phút khi đang mở, nên bấm Lưu xong khoảng 1 phút là người dùng thấy. Mỗi người đóng xong sẽ không thấy lại cho tới khi bạn đổi nội dung.</span></p>';
echo '<form method="post"><input type="hidden" name="csrf" value="' . h(csrf()) . '"><input type="hidden" name="action" value="announce">'
    . '<p><label><input type="checkbox" name="enabled" value="1"' . ($anOn ? ' checked' : '') . '> <b>Bật thông báo</b></label></p>'
    . '<label class="mut">Nhãn nổi bật, ví dụ ƯU ĐÃI -20% (tối đa 24 ký tự, để trống = không hiện)</label><input name="badge" maxlength="24" style="width:100%;margin:4px 0 10px" value="' . h($an['badge'] ?? '') . '">'
    . '<label class="mut">Tiêu đề (tối đa 80 ký tự)</label><input name="title" maxlength="80" style="width:100%;margin:4px 0 10px" value="' . h($an['title'] ?? '') . '">'
    . '<label class="mut">Nội dung (tối đa 600 ký tự, xuống dòng được)</label><textarea name="body" maxlength="600" rows="5" style="width:100%;margin:4px 0 10px">' . h($an['body'] ?? '') . '</textarea>'
    . '<div class="row" style="align-items:flex-end"><label style="flex:1;min-width:160px">Nút chính: chữ<input name="button_text" maxlength="30" value="' . h($an['button_text'] ?? '') . '"></label>'
    . '<label style="flex:2;min-width:260px">Nút chính: link https (để trống = ẩn nút chính)<input name="button_url" value="' . h($an['button_url'] ?? '') . '" placeholder="https://zalo.me/0979007367"></label></div>'
    . '<div class="row" style="align-items:flex-end;margin-top:10px"><label>Nút phụ: chữ (để trống = ẩn nút phụ)<input name="secondary_text" maxlength="20" value="' . h(array_key_exists('secondary_text', $an) ? (string)$an['secondary_text'] : 'Để sau') . '"></label>'
    . '<label>Hết hiệu lực sau ngày<input type="date" name="expires" value="' . ($anExp > 0 ? h(date('Y-m-d', $anExp)) : '') . '"></label>'
    . '<label style="align-self:center"><input type="checkbox" name="reshow" value="1"> Hiện lại cho cả người đã đóng</label></div>'
    . '<p class="mut" style="margin-top:10px">Chỉ hiện cho người đang dùng thử, người dùng key dùng thử/trải nghiệm và người đã hết hạn dùng thử. Không hiện cho người đã mua gói.</p>'
    . '<p style="margin-top:8px"><button type="submit">Lưu thông báo</button></p></form></div>';

// Cấp key tay
echo '<h2>Cấp key tay</h2><div class="card"><form method="post" class="row"><input type="hidden" name="csrf" value="' . h(csrf()) . '"><input type="hidden" name="action" value="manual_key">'
    . '<label style="flex:1;min-width:240px">Mã máy<input name="machine" placeholder="MH-XXXX-XXXX-XXXX-XXXX" required pattern="[Mm][Hh]-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}"></label>'
    . '<label>Gói<select name="plan" id="plan">';
foreach ($c['plans'] as $code => $p) {
    echo '<option value="' . h($code) . '" data-price="' . (int)$p['price'] . '">' . h($p['name']) . ' (' . h(money((int)$p['price'])) . ')</option>';
}
echo '</select></label><label>Số tiền đã nhận (ghi sổ)<input name="amount" id="amount" value="' . h((string)(int)(reset($c['plans'])['price'] ?? 0)) . '" inputmode="numeric"></label>'
    . '<label style="flex:1;min-width:200px">Ghi chú (tên khách...)<input name="note" maxlength="120"></label><button type="submit">Tạo key</button></form>'
    . '<p class="mut" style="margin-bottom:0">Key có hạn phải được khách nhập trong vòng 30 ngày kể từ hôm nay; thời hạn gói tính từ lúc kích hoạt và được cộng dồn nếu đang còn hạn.</p></div>';

// Giao dịch lạ
if ($badTxRows) {
    echo '<h2>Giao dịch cần xem</h2><div class="tablewrap"><table><tr><th>Thời gian</th><th>Số tiền</th><th>Mã trong nội dung</th><th>Nội dung chuyển khoản</th><th>Kết quả</th></tr>';
    $res = ['unknown_order' => 'Không có đơn tương ứng', 'no_code' => 'Không có mã đơn', 'duplicate_payment' => 'Trả trùng đơn đã thanh toán'];
    foreach ($badTxRows as $t) {
        echo '<tr><td>' . h(date('d/m/Y H:i', (int)$t['created_at'])) . '</td><td>' . h(money((int)$t['amount'])) . '</td><td>' . h($t['code']) . '</td><td>' . h($t['content']) . '</td><td>' . h($res[$t['result']] ?? $t['result']) . '</td></tr>';
    }
    echo '</table></div>';
}

// Đơn hàng
echo '<h2>Đơn hàng</h2><form method="get" class="row" style="margin-bottom:10px;align-items:center"><input name="q" value="' . h($search) . '" placeholder="Mã đơn, mã máy hoặc ghi chú" style="min-width:300px"><button type="submit">Tìm</button>'
    . ($search !== '' ? '<a class="btn ghost" href="admin.php">Xoá lọc</a>' : '') . '<span class="mut">' . $total . ' đơn</span></form>';
echo '<div class="tablewrap"><table><tr><th>Thời gian</th><th>Mã đơn</th><th>Gói</th><th>Số tiền</th><th>Trạng thái</th><th>Mã máy</th><th>Thời hạn gói</th><th>Key / thao tác</th></tr>';
if (!$orders) {
    echo '<tr><td colspan="8" class="mut">Chưa có đơn nào.</td></tr>';
}
foreach ($orders as $i => $o) {
    $status = $o['status'] === 'pending' && (int)$o['expires_at'] < time() ? 'expired' : $o['status'];
    $plan = $c['plans'][$o['plan']] ?? ['name' => $o['plan'], 'days' => null];
    $manual = ($o['sepay_id'] ?? '') === 'manual';
    echo '<tr><td>' . h(date('d/m/Y H:i', (int)$o['created_at'])) . '</td><td>' . h($o['code']) . '</td><td>' . h($plan['name']) . '</td>'
        . '<td>' . h(money((int)($status === 'paid' ? ($o['paid_amount'] ?? 0) : $o['amount']))) . '</td>'
        . '<td><span class="tag t-' . h($status) . '">' . h($statusLabel[$status] ?? $status) . '</span>' . ($manual ? ' <span class="tag t-manual">Tay</span>' : '')
        . ($o['note'] ? '<div class="mut">' . h($o['note']) . '</div>' : '') . '</td>'
        . '<td class="key">' . h($o['machine_id']) . '</td><td>' . ($plan['days'] ? (int)$plan['days'] . ' ngày' : 'Vĩnh viễn') . '</td><td>';
    if ($o['key']) {
        echo '<span class="key" id="k' . $i . '">' . h(mb_substr((string)$o['key'], 0, 22)) . '…</span> <button type="button" class="ghost sm" data-copy-text="' . h($o['key']) . '">Sao chép key</button>';
    }
    if ($status === 'review' || $status === 'pending' || $status === 'expired') {
        echo '<form method="post" style="display:inline" data-confirm="Tạo key cho đơn này?"><input type="hidden" name="csrf" value="' . h(csrf()) . '"><input type="hidden" name="action" value="approve"><input type="hidden" name="code" value="' . h($o['code']) . '"><button class="ok sm" type="submit">Duyệt &amp; cấp key</button></form> ';
    }
    if ($status !== 'paid' && $status !== 'cancelled') {
        echo '<form method="post" style="display:inline" data-confirm="Huỷ đơn này?"><input type="hidden" name="csrf" value="' . h(csrf()) . '"><input type="hidden" name="action" value="cancel"><input type="hidden" name="code" value="' . h($o['code']) . '"><button class="ghost sm" type="submit">Huỷ</button></form>';
    }
    echo '</td></tr>';
}
echo '</table></div>';
if ($pages > 1) {
    $qs = $search !== '' ? '&q=' . urlencode($search) : '';
    echo '<div class="pager">' . ($page > 1 ? '<a class="btn ghost sm" href="?p=' . ($page - 1) . $qs . '">‹ Trước</a>' : '') . '<span class="mut">Trang ' . $page . '/' . $pages . '</span>'
        . ($page < $pages ? '<a class="btn ghost sm" href="?p=' . ($page + 1) . $qs . '">Sau ›</a>' : '') . '</div>';
}
echo '<p class="mut" style="margin-top:24px">Bảng giá hiện hành lấy từ config.php (muốn đổi giá hoặc thêm gói thì sửa file đó). Tự đăng xuất sau 2 giờ không thao tác.</p>';

page_foot($nonce, <<<'JS'
function copy(t,b){navigator.clipboard.writeText(t).then(function(){var o=b.textContent;b.textContent='Đã chép!';setTimeout(function(){b.textContent=o},1500)}).catch(function(){prompt('Sao chép key:',t)})}
document.addEventListener('submit',function(e){var m=e.target.dataset&&e.target.dataset.confirm;if(m&&!confirm(m))e.preventDefault()});
document.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;
 if(b.dataset.copyText){copy(b.dataset.copyText,b)}
 else if(b.dataset.copy){copy(document.getElementById(b.dataset.copy).textContent.trim(),b)}});
var p=document.getElementById('plan'),a=document.getElementById('amount');
if(p&&a){p.addEventListener('change',function(){a.value=p.selectedOptions[0].dataset.price})}
JS);
