# Bản quyền & kích hoạt key online — Video AI - Mr. Huỳnh

## 1. Cách hoạt động

- **Máy chủ bản quyền** nằm trong thư mục `license-server`, chạy trên Cloudflare Workers + D1. Gói miễn phí đủ cho vài nghìn khách và không cần thuê VPS. Máy chủ dùng chung được cho nhiều phần mềm nhờ cột `product`, nên sau này tool Voice AI có thể dùng chung.
- **Giấy phép có chữ ký số Ed25519.** Phần mềm chỉ giữ *khóa công khai*: nó kiểm tra được giấy phép nhưng không tự tạo ra được. Vì vậy khách không sửa được ngày hết hạn và không chép giấy phép sang máy khác được.
- **Mã máy** được tạo từ MachineGuid của Windows và số serial ổ đĩa, rồi băm ra. Cài lại phần mềm vẫn giữ nguyên mã máy.
- **Hai gói:**
  - **Miễn phí vĩnh viễn:** không cần key. Khách dùng đủ chức năng và đăng nhập được nhiều tài khoản, nhưng **mỗi lần chỉ tạo 1 tác vụ**; tác vụ xong mới nhập được prompt tiếp. Giới hạn này khóa ở cả giao diện lẫn bộ máy chạy.
  - **Chuyên nghiệp:** đủ tính năng, chạy hàng loạt, song song nhiều tài khoản. Cần key.
- **Key hết hạn hoặc bị khóa:** phần mềm tự về gói Miễn phí, không chặn mở phần mềm.
- **Kiểm tra lại:** phần mềm hỏi máy chủ khi mở và cứ mỗi 3 giờ. Khi mất mạng vẫn dùng tiếp được tối đa 3 ngày. Nếu khách lùi đồng hồ máy, phần mềm phát hiện và bắt kiểm tra online.
- **Gia hạn cộng dồn:** khách đang còn hạn mà nhập thêm key thì số ngày của key mới được cộng vào hạn hiện tại, không mất ngày nào.
- **Mỗi key dùng cho 1 máy.** Khách tự chuyển sang máy mới được 1 lần mỗi 30 ngày, và máy cũ mất bản quyền ở lần kiểm tra tiếp theo. Trường hợp khác, bạn bấm "Đổi máy" trong trang quản trị.
- **Bảng giá** lưu trên máy chủ. Bạn đổi giá trong trang quản trị là phần mềm của khách tự cập nhật, không cần build lại.

## 2a. Cài trên hosting của bạn, dùng chung với Voice AI (khuyến nghị)

Xem `hosting/HUONG-DAN-HOSTING.txt`. Tóm tắt:
1. Chạy `hosting\chuan-bi-hosting.bat`.
2. Tải 2 thư mục trong `hosting\upload\` lên hosting `active.mrhuynh.net`.
3. Đổi webhook SePay sang `https://active.mrhuynh.net/webhook.php`.
4. Build lại phần mềm.

Sau đó trang quản trị chung nằm ở `https://active.mrhuynh.net/admin/` và quản lý được cả Video AI lẫn Voice AI.

## 2. (Cách khác) Cài máy chủ trên Cloudflare (làm 1 lần, khoảng 10 phút)

1. Chạy `build Windows.bat` một lần để có Python.
2. Chạy `license-server\setup.bat`. Script tự làm các việc sau:
   - Cài Node.js và công cụ Cloudflare.
   - Tạo khóa ký và ghi khóa công khai vào phần mềm.
   - Mở trình duyệt để bạn **tự đăng nhập hoặc đăng ký Cloudflare (miễn phí)**.
   - Tạo cơ sở dữ liệu, đặt mật khẩu quản trị, đưa máy chủ lên mạng, rồi ghi địa chỉ máy chủ vào `videoai\license_config.json`.
3. Cuối cùng script in ra **địa chỉ trang quản trị** và **mật khẩu**. Bạn lưu lại hai thông tin này.
4. Chạy lại `build Windows.bat`. Bản exe build ra lúc này đã khóa key.

> **Giữ bí mật** hai file `license-server\.signing_key.jwk` và `license-server\.setup_state.json`, và sao lưu chúng ra USB hoặc Drive riêng. Nếu mất khóa ký, bạn phải tạo khóa mới và phát hành lại phần mềm cho mọi khách.

Khi chưa cài máy chủ (`license_config.json` còn trống), phần mềm chạy ở **chế độ phát triển**, không khóa gì. Khi build, `build Windows.bat` sẽ cảnh báo trường hợp này.

## 3. Bán hằng ngày (cấp key tay qua Zalo)

1. Khách bấm **"Mua gói này"**. Phần mềm mở Zalo của bạn và chép sẵn tin nhắn gồm gói và mã máy; khách chỉ cần dán vào Zalo và gửi.
2. Khách chuyển khoản. Bạn mở **trang quản trị › Tạo key**, chọn gói, ghi tên hoặc SĐT khách, rồi bấm Tạo. Key được tự chép sẵn.
3. Gửi key cho khách. Khách nhập key vào ô kích hoạt, xong.

Trang quản trị còn có các chức năng:
- Tìm key theo tên, SĐT hoặc mã máy.
- Cộng hoặc trừ ngày cho key.
- Khóa key (dùng khi khách hoàn tiền hoặc chia sẻ key). Phần mềm của khách ngừng hoạt động trong tối đa khoảng 3 giờ.
- Đổi máy cho khách.
- Cộng thêm ngày dùng thử.
- Xem doanh thu hôm nay, 30 ngày và tổng.
- Xem nhật ký kích hoạt.

## 3a. Cập nhật online cho khách

Phần mềm (từ bản 1.5.0) tự hỏi `https://active.mrhuynh.net/video/v1/app/version` khi mở và mỗi 3 giờ.

1. Tăng số phiên bản trong `videoai/core/paths.py` (`APP_VERSION`), ghi `CHANGELOG.txt`, chạy `build Windows.bat`
   (cần Inno Setup) → `dist\VideoAI-MrHuynh-Setup-x.y.z.exe`.
2. cPanel › File Manager › `active.mrhuynh.net/video/download/` › Upload file Setup đó.
3. Trang quản trị › Video AI › **Cập nhật phần mềm** › chọn file (số phiên bản tự điền) › ghi "Có gì mới" › **Phát hành**.
4. Khách thấy thông báo trong vòng 3 giờ (hoặc ngay khi mở phần mềm / bấm nút "Kiểm tra cập nhật" dưới menu),
   phần mềm tự tải, kiểm tra SHA-256, cài và mở lại.

- **Bắt buộc cập nhật**: tick "Bắt buộc mọi người" hoặc điền "Bắt buộc với bản thấp hơn" (vd. 1.6.0) → không có nút "Để sau".
- **Bản lỗi**: bấm **Ngừng phát** ở lịch sử → khách nhận lại bản đang bật cao nhất còn lại.
- Xóa bớt file Setup cũ trong `video/download/` cho đỡ tốn dung lượng (giữ bản đang phát).
- Khách đang dùng bản trước 1.5.0 không có cập nhật online → gửi bộ cài 1.5.0 cho họ một lần.

## 3b. Video hướng dẫn cho từng chức năng

Vào **trang quản trị › Video hướng dẫn**, dán link YouTube cho từng chức năng (Tạo ảnh Flow, Tạo Video Flow, Kho ảnh tham chiếu…) rồi bấm **Lưu**.

- Phần mềm của khách hiện nút đỏ **"Xem Video hướng dẫn"** cạnh tên trang. Bấm vào là mở đúng video của chức năng đó.
- Chức năng nào để trống link thì nút bị ẩn ở trang đó.
- Phần mềm tải link mới mỗi lần mở, không cần build lại. Link cũ vẫn dùng được khi khách mất mạng.

## 4. Bật thanh toán tự động (tùy chọn): VietQR + SePay

Khi bật, khách bấm "Mua gói này" thì phần mềm hiện mã QR có sẵn số tiền và nội dung chuyển khoản (ví dụ `VAI8K2P4QX`). Khách chuyển khoản, SePay báo về máy chủ, máy chủ tự tạo key và phần mềm tự kích hoạt trong vài giây. Bạn không cần làm gì.

1. Đăng ký **sepay.vn** và liên kết tài khoản ngân hàng nhận tiền. SePay hỗ trợ tài khoản cá nhân của MB, VCB, ACB, TCB, VPB, BIDV…
2. Chạy lại `license-server\setup.bat` và trả lời **c** khi được hỏi bật thanh toán. Nếu trước đó đã trả lời không, xóa dòng `"payment_asked"` trong `.setup_state.json` rồi chạy lại.
3. Trong SePay, vào **Webhooks › Thêm webhook**:
   - URL: `https://<máy-chủ>/v1/sepay`
   - Kiểu chứng thực: **API Key**, dán khóa mà setup đã in ra.
   - Sự kiện: tiền vào.

Máy chủ tự xử lý ba trường hợp: chuyển thiếu tiền thì không cấp key; SePay gửi trùng giao dịch thì chỉ cấp 1 key; đơn quá 24 giờ thì hết hạn.

## 5. Bảng giá hiện tại & tham mưu

| Gói | Giá | Quy ra / tháng |
|---|---|---|
| Miễn phí | 0đ, vĩnh viễn | mỗi lần 1 tác vụ |
| Chuyên nghiệp 1 tháng | 80.000đ | 80.000đ |
| Chuyên nghiệp 3 tháng | 220.000đ | ~73.000đ |
| Chuyên nghiệp 6 tháng | 450.000đ | 75.000đ |
| Chuyên nghiệp 1 năm | 900.000đ | 75.000đ |

Lưu ý: với mức giá này, **gói 6 tháng và 1 năm tính theo tháng lại đắt hơn gói 3 tháng**, nên khách tính kỹ sẽ chỉ mua gói 3 tháng nhiều lần. Muốn khách mua gói dài thì giá nên giảm dần theo thời hạn, ví dụ 6 tháng 400.000đ (~67.000đ/tháng) và 1 năm 720.000đ (60.000đ/tháng). Đổi giá trong trang quản trị › Bảng giá, không cần build lại phần mềm.

Đề xuất khác:
- **Gói Miễn phí là "mồi" tốt:** khách thấy chất lượng thật, rồi vướng giới hạn 1 tác vụ khi cần chạy hàng loạt. Phần mềm đã hiện nút "Nâng cấp Chuyên nghiệp" đúng lúc khách bị chặn.
- **Khuyến mãi** thì không cần sửa code:
  - Combo với Voice AI: tạo key với giá riêng trong ô "Giá bán".
  - Cộng tác viên: ghi tên CTV vào "Ghi chú" để đối soát hoa hồng.
- **Hoàn tiền:** nên cho hoàn trong 3 ngày đầu. Khi hoàn tiền thì bấm **Khóa** key.

## 6. Chống bẻ khóa

Chữ ký số và kiểm tra trên máy chủ đã chặn được các cách phổ biến: sửa ngày, chép sang máy khác, reset dùng thử và chia sẻ key. Bản PyInstaller vẫn có thể bị dịch ngược để gỡ đoạn kiểm tra. Muốn khó hơn thì build bằng **Nuitka**, dịch sang C. Không có cách nào chặn được 100%. Nên ưu tiên cập nhật thường xuyên, vì bản bẻ khóa sẽ không nhận được bản cập nhật Flow mới.

## 7. Chi phí

Cloudflare Workers miễn phí 100.000 yêu cầu mỗi ngày, D1 miễn phí 5 GB. Mỗi khách tạo khoảng 10 yêu cầu mỗi ngày, nên miễn phí đủ cho khoảng 10.000 khách đang dùng. Nếu vượt, gói trả phí là 5 USD/tháng.
