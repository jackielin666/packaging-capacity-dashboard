-- 問題：手動 insert 進 auth.users 的帳號登入時回 500
--       {"error_code":"unexpected_failure","msg":"Database error querying schema"}
--
-- 原因：Supabase Auth（GoTrue）把下列欄位讀成「不可為 NULL 的字串」。
--       用後台介面建帳號時預設寫入空字串，手動 insert 漏掉就變 NULL，
--       GoTrue 讀到 NULL 直接整個查詢失敗 —— 錯誤訊息看不出跟欄位有關。
--
-- 修法：全部補成空字串。對既有帳號無副作用。

update auth.users set
  confirmation_token         = coalesce(confirmation_token, ''),
  recovery_token             = coalesce(recovery_token, ''),
  email_change_token_new     = coalesce(email_change_token_new, ''),
  email_change               = coalesce(email_change, ''),
  email_change_token_current = coalesce(email_change_token_current, ''),
  phone_change               = coalesce(phone_change, ''),
  phone_change_token         = coalesce(phone_change_token, ''),
  reauthentication_token     = coalesce(reauthentication_token, '')
where confirmation_token is null
   or recovery_token is null
   or email_change_token_new is null
   or email_change is null
   or email_change_token_current is null
   or phone_change is null
   or phone_change_token is null
   or reauthentication_token is null;


-- 建立登入帳號的唯一入口。把上面那些欄位一次補齊，避免再踩同一個坑。
--
-- 使用者只認「帳號」，信箱是內部用的，所以這裡自動補上網域：
--   create_login('packer01', '密碼', '王小明', 'operator')
--   → 實際信箱 packer01@packing.local，使用者永遠看不到
create or replace function packing.create_login(
  p_account  text,
  p_password text,
  p_display  text,
  p_role     text default 'operator'
) returns uuid
language plpgsql
security definer
set search_path = pg_catalog, public, extensions
as $$
declare
  uid   uuid;
  mail  text := lower(p_account) || '@packing.local';
begin
  if p_role not in ('operator','manager','viewer') then
    raise exception '角色只能是 operator／manager／viewer，收到的是 %', p_role;
  end if;
  if length(p_password) < 8 then
    raise exception '密碼至少 8 個字元';
  end if;

  select id into uid from auth.users where email = mail;

  if uid is null then
    uid := gen_random_uuid();
    insert into auth.users (
      instance_id, id, aud, role, email, encrypted_password,
      email_confirmed_at, created_at, updated_at,
      raw_app_meta_data, raw_user_meta_data, is_sso_user, is_anonymous,
      -- 以下八欄一定要是空字串，不能留 NULL
      confirmation_token, recovery_token, email_change_token_new, email_change,
      email_change_token_current, phone_change, phone_change_token, reauthentication_token
    ) values (
      '00000000-0000-0000-0000-000000000000', uid, 'authenticated', 'authenticated',
      mail, extensions.crypt(p_password, extensions.gen_salt('bf')),
      now(), now(), now(),
      '{"provider":"email","providers":["email"]}'::jsonb,
      jsonb_build_object('display_name', p_display),
      false, false,
      '', '', '', '', '', '', '', ''
    );

    insert into auth.identities (
      id, user_id, provider_id, provider, identity_data, created_at, updated_at, last_sign_in_at
    ) values (
      gen_random_uuid(), uid, uid::text, 'email',
      jsonb_build_object('sub', uid::text, 'email', mail,
                         'email_verified', true, 'phone_verified', false),
      now(), now(), now()
    );
  else
    update auth.users
       set encrypted_password = extensions.crypt(p_password, extensions.gen_salt('bf')),
           updated_at = now()
     where id = uid;
  end if;

  insert into packing.members (user_id, display_name, role)
  values (uid, p_display, p_role)
  on conflict (user_id) do update
    set display_name = excluded.display_name, role = excluded.role;

  return uid;
end $$;

-- 這支函式能建帳號、能改密碼，絕對不可以從瀏覽器呼叫。
-- packing schema 開放給 Data API 後，未撤銷的函式會自動變成公開的 RPC 端點。
revoke all on function packing.create_login(text,text,text,text) from public, anon, authenticated;
grant execute on function packing.create_login(text,text,text,text) to service_role;

comment on function packing.create_login is
  '建立或更新登入帳號。只能由 service_role／SQL 編輯器呼叫，不對外開放。';
