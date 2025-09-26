import cv2, numpy as np


def unsharp_mask(image, ksize=(5, 5), sigma=1.0, amount=1.0, threshold=0):
    blurred = cv2.GaussianBlur(image, ksize, sigma)
    sharpened = cv2.addWeighted(image, 1 + amount, blurred, -amount, 0)
    if threshold > 0:
        low_contrast_mask = np.absolute(image - blurred) < threshold
        np.copyto(sharpened, image, where=low_contrast_mask)
    return sharpened


def auto_white_balance(img):
    # Simple gray-world assumption
    result = img.copy().astype(np.float32)
    avg_b, avg_g, avg_r = (
        np.mean(result[:, :, 0]),
        np.mean(result[:, :, 1]),
        np.mean(result[:, :, 2]),
    )
    avg = (avg_b + avg_g + avg_r) / 3.0
    result[:, :, 0] *= avg / (avg_b + 1e-6)
    result[:, :, 1] *= avg / (avg_g + 1e-6)
    result[:, :, 2] *= avg / (avg_r + 1e-6)
    return np.clip(result, 0, 255).astype(np.uint8)
