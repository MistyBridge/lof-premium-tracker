-- 金快查 用户中心 数据库初始化
-- 在 Supabase SQL Editor 中执行

-- 1. profiles 表（用户扩展信息）
CREATE TABLE public.profiles (
    id         uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email      text NOT NULL,
    nickname   text DEFAULT '',
    avatar_url text DEFAULT '',
    role       text NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    status     text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'banned')),
    created_at timestamptz NOT NULL DEFAULT now(),
    last_login timestamptz
);

-- 2. fund_favorites 表（基金收藏）
CREATE TABLE public.fund_favorites (
    user_id   uuid NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    fund_code varchar(6) NOT NULL,
    added_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, fund_code)
);

-- 3. user_settings 表（用户偏好设置）
CREATE TABLE public.user_settings (
    user_id        uuid PRIMARY KEY REFERENCES public.profiles(id) ON DELETE CASCADE,
    dark_mode      text NOT NULL DEFAULT 'light',
    default_page   text NOT NULL DEFAULT 'lof',
    page_size      integer NOT NULL DEFAULT 20 CHECK (page_size BETWEEN 10 AND 100),
    show_suspended boolean NOT NULL DEFAULT false,
    columns_config jsonb
);

-- 4. 注册时自动创建 profiles 行
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = ''
AS $$
BEGIN
  INSERT INTO public.profiles (id, email)
  VALUES (NEW.id, NEW.email);
  RETURN NEW;
END;
$$;

-- 5. 绑定触发器
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- 6. 开启 RLS（行级安全）
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fund_favorites ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_settings ENABLE ROW LEVEL SECURITY;

-- 7. RLS 策略：用户只能读写自己的数据
CREATE POLICY "Users read own profile" ON public.profiles
    FOR SELECT USING (auth.uid() = id);
CREATE POLICY "Users update own profile" ON public.profiles
    FOR UPDATE USING (auth.uid() = id);

CREATE POLICY "Users manage own favorites" ON public.fund_favorites
    FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "Users manage own settings" ON public.user_settings
    FOR ALL USING (auth.uid() = user_id);
