<?php
declare(strict_types=1);
require (getenv('ACTIVE_PRIVATE') ?: __DIR__ . '/../active_private') . '/lib.php';

// API cho app Voice AI - Mr.Huỳnh: /api/plans, /api/orders, /api/orders/{code}, /api/app/version
try {
    $c = cfg();
    $path = rtrim((string)parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH), '/');
    $method = $_SERVER['REQUEST_METHOD'] ?? 'GET';

    if ($path === '' || $path === '/') {
        header('Content-Type: text/plain; charset=utf-8');
        echo "Voice AI - Mr.Huỳnh license server\n";
        exit;
    }

    if ($path === '/api/ping') {
        json_out(['ok' => true]);
    }

    if ($path === '/api/plans' && $method === 'GET') {
        $plans = [];
        foreach ($c['plans'] as $code => $p) {
            if (($p['sale'] ?? true) === false) {
                continue;
            }
            $plans[] = ['code' => $code, 'name' => $p['name'], 'days' => $p['days'], 'price' => (int)$p['price']];
        }
        json_out(['plans' => $plans, 'expires_minutes' => (int)$c['order_ttl_minutes']]);
    }

    if ($path === '/api/app/announcement' && $method === 'GET') {
        // Thông báo popup do admin soạn trong admin.php (announcement.json). Chỉ trả khi đang bật và chưa hết hạn.
        $f = __DIR__ . '/announcement.json';
        $a = is_file($f) ? json_decode((string)file_get_contents($f), true) : null;
        $exp = (int)($a['expires_at'] ?? 0);
        if (!is_array($a) || empty($a['enabled']) || empty($a['id']) || ($exp > 0 && $exp < time())) {
            json_out(['enabled' => false]);
        }
        $url = (string)($a['button_url'] ?? '');
        json_out([
            'enabled' => true,
            'id' => (string)$a['id'],
            'badge' => mb_substr((string)($a['badge'] ?? ''), 0, 24),
            'title' => mb_substr((string)($a['title'] ?? ''), 0, 80),
            'body' => mb_substr((string)($a['body'] ?? ''), 0, 600),
            'button_text' => mb_substr((string)($a['button_text'] ?? ''), 0, 30),
            'button_url' => str_starts_with($url, 'https://') ? $url : '',
            'secondary_text' => mb_substr((string)($a['secondary_text'] ?? 'Để sau'), 0, 20),
            'expires_at' => $exp,
        ]);
    }

    if ($path === '/api/app/video' && $method === 'GET') {
        // Link video hướng dẫn do admin đặt trong admin.php (video.json). Chỉ nhận https.
        $f = __DIR__ . '/video.json';
        $a = is_file($f) ? json_decode((string)file_get_contents($f), true) : null;
        $url = is_array($a) ? (string)($a['url'] ?? '') : '';
        json_out(['url' => str_starts_with($url, 'https://') ? $url : '']);
    }

    if ($path === '/api/app/version' && $method === 'GET') {
        $f = __DIR__ . '/version.json';
        $v = is_file($f) ? json_decode((string)file_get_contents($f), true) : null;
        if (!is_array($v) || empty($v['version'])) {
            json_out(['version' => '0.0.0']);
        }
        $url = (string)($v['url'] ?? '');
        if (!str_starts_with($url, 'https://')) {
            $url = '';
        }
        json_out([
            'version' => (string)$v['version'],
            'url' => $url,
            // Link .dmg cho macOS (tuỳ chọn); app Mac dùng url_mac, bỏ trống = chưa có bản Mac.
            'url_mac' => str_starts_with((string)($v['url_mac'] ?? ''), 'https://') ? (string)$v['url_mac'] : '',
            // Bản Mac phát hành riêng (trang quản trị › Voice AI › Phát hành › macOS): số phiên bản + link .dmg theo chip.
            'version_mac' => preg_match('/^\d{1,4}(\.\d{1,4}){1,3}$/', (string)($v['version_mac'] ?? '')) ? (string)$v['version_mac'] : '',
            'url_mac_apple' => str_starts_with((string)($v['url_mac_apple'] ?? ''), 'https://') ? (string)$v['url_mac_apple'] : '',
            'url_mac_intel' => str_starts_with((string)($v['url_mac_intel'] ?? ''), 'https://') ? (string)$v['url_mac_intel'] : '',
            'highlights' => array_slice(array_map('strval', (array)($v['highlights'] ?? [])), 0, 6),
            // Chữ ký do công cụ ký tạo (trên máy chủ chỉ chuyển tiếp, không tự ký): app dùng để cập nhật tự động.
            'sha256' => preg_match('/^[0-9a-f]{64}$/i', (string)($v['sha256'] ?? '')) ? strtolower((string)$v['sha256']) : '',
            'signature' => preg_match('#^[A-Za-z0-9+/=]{60,120}$#', (string)($v['signature'] ?? '')) ? (string)$v['signature'] : '',
        ]);
    }

    if ($path === '/api/orders' && $method === 'POST') {
        $in = json_decode((string)file_get_contents('php://input'), true);
        if (!is_array($in)) {
            fail('Dữ liệu không hợp lệ.');
        }
        $machine = parse_machine((string)($in['machine_id'] ?? ''));
        $planCode = (string)($in['plan'] ?? '');
        if ($machine === null) {
            fail('Mã máy không hợp lệ.');
        }
        if (!isset($c['plans'][$planCode]) || ($c['plans'][$planCode]['sale'] ?? true) === false) {
            fail('Gói không tồn tại.');
        }
        $ip = (string)($_SERVER['REMOTE_ADDR'] ?? '?');
        $pdo = db();
        $pdo->prepare('DELETE FROM rate WHERE ts < ?')->execute([time() - 3600]);
        $n = $pdo->prepare('SELECT COUNT(*) FROM rate WHERE ip = ?');
        $n->execute([$ip]);
        if ((int)$n->fetchColumn() >= (int)$c['orders_per_hour_per_ip']) {
            fail('Bạn thao tác quá nhanh, vui lòng thử lại sau.', 429);
        }
        $machineText = 'MH-' . implode('-', str_split($machine, 4));
        $price = (int)$c['plans'][$planCode]['price'];

        // Dùng lại đơn đang chờ cùng máy + cùng gói + cùng giá để không tạo trùng.
        $q = $pdo->prepare('SELECT * FROM orders WHERE machine_id=? AND plan=? AND amount=? AND status="pending" AND expires_at>? ORDER BY created_at DESC LIMIT 1');
        $q->execute([$machineText, $planCode, $price, time()]);
        $o = $q->fetch();
        if (!$o) {
            $pdo->prepare('INSERT INTO rate (ip, ts) VALUES (?, ?)')->execute([$ip, time()]);
            for ($try = 0; $try < 5; $try++) {
                $code = order_code();
                try {
                    $pdo->prepare('INSERT INTO orders (code, machine_id, plan, amount, status, created_at, expires_at) VALUES (?,?,?,?,"pending",?,?)')
                        ->execute([$code, $machineText, $planCode, $price, time(), time() + 60 * (int)$c['order_ttl_minutes']]);
                    break;
                } catch (PDOException $e) {
                    if ($try === 4) {
                        throw $e;
                    }
                }
            }
            $q = $pdo->prepare('SELECT * FROM orders WHERE code=?');
            $q->execute([$code]);
            $o = $q->fetch();
            telegram("🛒 Đơn mới (chờ thanh toán)\nGói: {$c['plans'][$planCode]['name']}\nSố tiền: " . money($price) . "\nMã đơn: {$o['code']}\nMáy: $machineText");
        }
        json_out(order_public($o, false));
    }

    if (preg_match('#^/api/orders/([A-Z0-9]{6,20})$#', $path, $m) && $method === 'GET') {
        $machine = parse_machine((string)($_GET['machine_id'] ?? ''));
        if ($machine === null) {
            fail('Mã máy không hợp lệ.');
        }
        $q = db()->prepare('SELECT * FROM orders WHERE code=?');
        $q->execute([$m[1]]);
        $o = $q->fetch();
        // Chỉ máy đã tạo đơn mới đọc được đơn (và key).
        if (!$o || parse_machine($o['machine_id']) !== $machine) {
            fail('Không tìm thấy đơn.', 404);
        }
        json_out(order_public($o, true));
    }

    fail('Không tìm thấy.', 404);
} catch (Throwable $e) {
    log_line('index.php: ' . $e->getMessage());
    json_out(['error' => 'Lỗi máy chủ, vui lòng thử lại sau.'], 500);
}
