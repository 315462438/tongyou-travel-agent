# 踩坑：SQLAlchemy 的列默认值在 commit 前是 None

**发现时间**：2026-08-04（图片上传上线后线上自检立刻暴露）
**涉及文件**：`backend/app/api/upload_api.py`

## 现象

上传接口返回 200，`{"id": "847c61...", "url": "/api/uploads/847c61..."}` 看着完全正常。
但拿这个 URL 取图**必定 404**（`{"detail":"图片已失效"}`）。

上服务器一看，磁盘上只有一个文件：

```
-rw-r--r-- 1 ubuntu ubuntu 208 Aug  4 16:00 None.png
```

## 原因

```python
class TravelUpload(Base):
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
```

`default=_uuid` 是**列默认值**——SQLAlchemy 在 **INSERT 时**才求值。所以：

```python
row = TravelUpload(user_id=..., mime=mime, size=0)
target = stored_path(row.id, mime)   # ← row.id 此刻是 None！文件写成 None.png
...
db.add(row); db.commit()             # ← 到这里 id 才被填上真 uuid
return {"id": row.id, ...}           # ← 返回的是真 id，和磁盘上的名字对不上
```

两个后果，第二个更严重：

1. **取图永远 404** —— 响应里的 id 与落盘文件名不一致。
2. **所有人的图片互相覆盖** —— 全站每次上传都写同一个 `None.png`。
   如果当时没做「上传完立刻取回」的自检，这个数据损坏会一直潜伏。

## 解决

需要在 INSERT 之前使用主键时，**自己先生成**，别依赖列默认值：

```python
upload_id = _uuid()
row = TravelUpload(id=upload_id, user_id=user.id, mime=mime, size=0)
target = stored_path(upload_id, mime)
```

（另一条路是 `db.add(row); db.flush()` 后再用 `row.id`，但那样文件写入就被绑进了
事务边界，失败清理更绕。显式生成更直白。）

## 教训

1. **`default=` 不是「构造时赋值」。** 凡是「在 commit 前就要用到主键」的场景
   （拿 id 拼路径、拼 URL、发消息、写外部系统），都要自己生成 id。
   这一类 bug 的共同特征是**接口返回一切正常**，问题只在别处显形。
2. **上线自检必须做「写完立刻读回」的闭环。** 只验 `POST` 返回 200 完全看不出问题；
   这次是紧接着 `GET` 那张图才当场暴露。凡是写入类接口，自检都要跟一次回读。

## 回归测试

`backend/tests/test_admin_manage.py`：

- `test_upload_file_lands_at_the_returned_id` —— 落盘路径必须与返回 id 一致，
  且 `None.png` 不得存在
- `test_two_uploads_do_not_overwrite_each_other` —— 两次上传必须产生两个文件
