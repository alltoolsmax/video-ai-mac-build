<?php
declare(strict_types=1);
// API bản quyền Video AI - Mr. Huỳnh:  /video/v1/plans · guides · app/version · activate · check · order · sepay
require (getenv('VIDEOAI_PRIVATE') ?: __DIR__ . '/../../active_private/video') . '/lib.php';

use function VideoAI\{api_activate, api_check, api_guides, api_version, public_key_b64url, api_order, api_order_status, api_plans, client_ip, fail,
    handle_payment, json_out, limited, log_line, request_auth_header, sepay_authorized, valid_machine};

try {
    $path = (string)parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);
    $pos = strpos($path, '/v1/');
    $route = $pos === false ? '' : rtrim(substr($path, $pos), '/');
    $method = $_SERVER['REQUEST_METHOD'] ?? 'GET';

    if ($route === '') {
        header('Content-Type: text/plain; charset=utf-8');
        echo "Video AI - Mr. Huynh license server\n";
        exit;
    }
    if ($route === '/v1/plans') {
        api_plans();
    }
    if ($route === '/v1/pubkey') {                 // khóa CÔNG KHAI (an toàn để công khai) — script build tự điền vào phần mềm
        json_out(['ok' => true, 'product' => 'videoai', 'public_key' => public_key_b64url()]);
    }
    if ($route === '/v1/app/version') {
        api_version();
    }
    if ($route === '/v1/guides') {
        api_guides();
    }
    if ($route === '/v1/order' && $method === 'GET') {
        api_order_status((string)($_GET['code'] ?? ''), (string)($_GET['machine'] ?? ''));
    }
    if ($route === '/v1/sepay' && $method === 'POST') {          // webhook riêng cho Video AI (nếu muốn dùng)
        if (!sepay_authorized(request_auth_header())) {
            json_out(['success' => false, 'error' => 'unauthorized'], 401);
        }
        $d = json_decode((string)file_get_contents('php://input'), true);
        json_out(['success' => true, 'result' => is_array($d) ? handle_payment($d) : 'bad json']);
    }
    if ($method !== 'POST') {
        fail('not_found', 'Không có', 404);
    }
    if (limited('api:' . client_ip(), 40)) {
        fail('rate', 'Bạn thao tác quá nhanh, thử lại sau 1 phút.', 429);
    }
    $b = json_decode((string)file_get_contents('php://input'), true);
    if (!is_array($b) || ($b['product'] ?? 'videoai') !== 'videoai') {
        fail('bad_request', 'Dữ liệu không hợp lệ');
    }
    if (!valid_machine($b['machine'] ?? null)) {
        fail('bad_request', 'Mã máy không hợp lệ');
    }
    if ($route === '/v1/activate') {
        if (limited('act:' . client_ip(), 12)) {
            fail('rate', 'Nhập sai quá nhiều lần, thử lại sau 1 phút.', 429);
        }
        api_activate($b);
    }
    if ($route === '/v1/check') {
        api_check($b);
    }
    if ($route === '/v1/order') {
        api_order($b);
    }
    fail('not_found', 'Không có', 404);
} catch (Throwable $e) {
    log_line('video/index.php: ' . $e->getMessage());
    json_out(['ok' => false, 'code' => 'server', 'message' => 'Lỗi máy chủ, vui lòng thử lại sau.'], 500);
}
