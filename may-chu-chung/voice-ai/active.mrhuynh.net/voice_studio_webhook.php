<?php
declare(strict_types=1);
require (getenv('ACTIVE_PRIVATE') ?: __DIR__ . '/../active_private') . '/lib.php';

// Webhook SePay: khi tiền về, tìm đơn theo mã trong nội dung chuyển khoản, tạo key, báo Telegram.

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

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    header('Content-Type: text/plain; charset=utf-8');
    echo "OK\n";
    exit;
}

try {
    $c = cfg();
    $expected = 'Apikey ' . trim((string)$c['sepay_api_key']);
    if (!hash_equals($expected, trim(request_auth_header()))) {
        log_line('Webhook bị từ chối: sai API Key');
        json_out(['success' => false, 'error' => 'unauthorized'], 401);
    }

    $d = json_decode((string)file_get_contents('php://input'), true);
    if (!is_array($d)) {
        json_out(['success' => false, 'error' => 'bad json'], 400);
    }
    if (($d['transferType'] ?? 'in') !== 'in') {
        json_out(['success' => true]);
    }

    $sepayId = (string)($d['id'] ?? '');
    $amount = (int)($d['transferAmount'] ?? 0);
    $content = (string)($d['content'] ?? '');
    if ($sepayId === '') {
        json_out(['success' => false, 'error' => 'no id'], 400);
    }

    // Mã đơn: ưu tiên trường code của SePay, nếu trống thì tìm trong nội dung.
    $prefix = preg_quote(strtoupper((string)($c['code_prefix'] ?? 'VAI')), '/');
    $code = strtoupper((string)($d['code'] ?? ''));
    if (!preg_match('/^' . $prefix . '[A-Z0-9]{8}$/', $code)) {
        $code = preg_match('/' . $prefix . '[A-Z0-9]{8}/i', $content, $m) ? strtoupper($m[0]) : '';
    }

    $pdo = db();
    $pdo->exec('BEGIN IMMEDIATE');
    try {
        $ins = $pdo->prepare('INSERT OR IGNORE INTO transactions (sepay_id, code, amount, content, result, created_at) VALUES (?,?,?,?,?,?)');
        $ins->execute([$sepayId, $code, $amount, mb_substr($content, 0, 300), 'received', time()]);
        if ($ins->rowCount() === 0) {          // SePay gọi lại cùng giao dịch: đã xử lý rồi
            $pdo->exec('COMMIT');
            json_out(['success' => true]);
        }

        $result = 'ignored';
        $msg = null;
        if ($code === '') {
            $result = 'no_code';
        } else {
            $q = $pdo->prepare('SELECT * FROM orders WHERE code=?');
            $q->execute([$code]);
            $o = $q->fetch();
            if (!$o) {
                $result = 'unknown_order';
                $msg = "⚠️ Nhận " . money($amount) . " có mã $code nhưng KHÔNG có đơn tương ứng.\nNội dung: $content\nGiao dịch SePay: $sepayId";
            } elseif ($o['status'] === 'paid') {
                $result = 'duplicate_payment';
                $msg = "⚠️ Đơn $code ĐÃ thanh toán trước đó, vừa nhận thêm " . money($amount) . ". Cần hoàn tiền thủ công.\nGiao dịch SePay: $sepayId";
            } elseif ($amount < (int)$o['amount']) {
                $result = 'underpaid';
                $pdo->prepare('UPDATE orders SET status="review", sepay_id=?, paid_amount=?, note=? WHERE code=?')
                    ->execute([$sepayId, $amount, 'Thiếu tiền', $code]);
                $msg = "⚠️ Đơn $code THIẾU TIỀN: nhận " . money($amount) . ", cần " . money((int)$o['amount']) . ".\nMáy: {$o['machine_id']}\nGói: {$o['plan']}\nHãy xử lý thủ công (cấp key bằng CapKey nếu đồng ý).";
            } else {
                $late = ((int)$o['expires_at'] < time()) ? ' (thanh toán sau khi đơn hết hạn)' : '';
                $over = $amount > (int)$o['amount'] ? ' (thừa ' . money($amount - (int)$o['amount']) . ')' : '';
                fulfil_order($o, $amount, $sepayId, trim($late . $over));
                $result = 'paid';
                $plan = $c['plans'][$o['plan']]['name'] ?? $o['plan'];
                $msg = "✅ ĐƠN MỚI ĐÃ THANH TOÁN$late$over\nGói: $plan\nSố tiền: " . money($amount) . "\nMã đơn: $code\nMáy: {$o['machine_id']}";
            }
        }
        $pdo->prepare('UPDATE transactions SET result=? WHERE sepay_id=?')->execute([$result, $sepayId]);
        $pdo->exec('COMMIT');
    } catch (Throwable $e) {
        $pdo->exec('ROLLBACK');
        throw $e;
    }

    if ($msg !== null) {
        telegram($msg);
    }
    log_line("Webhook $sepayId code=$code amount=$amount -> $result");
    json_out(['success' => true]);
} catch (Throwable $e) {
    log_line('Webhook LỖI: ' . $e->getMessage());
    try {
        telegram('❌ Webhook SePay gặp lỗi: ' . $e->getMessage());
    } catch (Throwable $ignored) {
    }
    json_out(['success' => false, 'error' => 'server error'], 500);   // 500 để SePay tự gửi lại
}
