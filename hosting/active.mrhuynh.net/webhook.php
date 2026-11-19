<?php
declare(strict_types=1);
// Webhook SePay CHUNG cho Voice AI + Video AI (1 tài khoản ngân hàng, 1 webhook).
//  - Mã đơn thuộc Video AI  → xử lý ở đây (tạo key Video AI).
//  - Mọi trường hợp khác    → chuyển NGUYÊN VẸN sang voice_studio_webhook.php của Voice AI (không sửa file đó).
// Khai báo trên SePay: https://active.mrhuynh.net/webhook.php · Chứng thực API Key (giống Voice AI).
$videoLib = (getenv('VIDEOAI_PRIVATE') ?: __DIR__ . '/../active_private/video') . '/lib.php';

if (($_SERVER['REQUEST_METHOD'] ?? '') === 'POST' && is_file($videoLib)) {
    require_once $videoLib;
    try {
        $d = json_decode((string)file_get_contents('php://input'), true);
        if (is_array($d) && \VideoAI\order_exists(\VideoAI\code_from($d))) {
            if (!\VideoAI\sepay_authorized(\VideoAI\request_auth_header())) {
                \VideoAI\log_line('Webhook chung: sai API Key');
                \VideoAI\json_out(['success' => false, 'error' => 'unauthorized'], 401);
            }
            $r = \VideoAI\handle_payment($d);
            \VideoAI\json_out(['success' => true, 'product' => 'videoai', 'result' => $r]);
        }
    } catch (Throwable $e) {
        \VideoAI\log_line('Webhook chung LỖI: ' . $e->getMessage());
        \VideoAI\json_out(['success' => false, 'error' => 'server error'], 500);   // SePay tự gửi lại
    }
}
require __DIR__ . '/voice_studio_webhook.php';
